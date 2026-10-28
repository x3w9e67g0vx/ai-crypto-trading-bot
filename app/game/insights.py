"""Micro lessons on orders and template reviews of closed trades."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd
from sqlalchemy.orm import Session

from app.core.db.models import Candle
from app.game.ai_view import is_pro
from app.game.analytics import log_event
from app.game.config import (
    AI_SYMBOLS,
    AI_VISIBILITY_DELAY_MS,
    BIG_POSITION_SHARE,
    CHART_TIMEFRAME,
    INSIGHT_MAX_AGE_MS,
    INSIGHT_MIN_CANDLES,
    MAX_TIPS_PER_ORDER,
)
from app.game.models import AiDecision, Player, Position
from app.services.indicator_service import IndicatorService

CANDLE_MS = 5 * 60 * 1000  # CHART_TIMEFRAME
CANDLE_HISTORY = 100

# Tip code -> lesson that explains it, in priority order.
TIP_LESSONS = {
    "overbought_buy": "07",
    "oversold_short": "07",
    "against_trend": "06",
    "no_stop": "04",
    "big_position": "03",
}


@dataclass(frozen=True)
class Indicators:
    rsi: float | None
    ema_fast: float
    ema_slow: float
    trend: str  # up | down


def indicators_at(db: Session, symbol: str, ts_ms: int) -> Indicators | None:
    """Indicators on the 5m candles closed by ts_ms; None if too few or too old."""
    rows = (
        db.query(Candle)
        .filter(
            Candle.symbol == symbol,
            Candle.timeframe == CHART_TIMEFRAME,
            Candle.timestamp <= ts_ms - CANDLE_MS,
        )
        .order_by(Candle.timestamp.desc())
        .limit(CANDLE_HISTORY)
        .all()
    )
    if len(rows) < INSIGHT_MIN_CANDLES or ts_ms - (rows[0].timestamp + CANDLE_MS) > INSIGHT_MAX_AGE_MS:
        return None
    frame = pd.DataFrame({"close": [row.close for row in reversed(rows)]}, dtype=float)
    last = IndicatorService(db).calculate_indicators(frame).iloc[-1]
    rsi = last["rsi"]
    # RSI is undefined when there were no losing candles at all.
    rsi = None if pd.isna(rsi) else float(rsi)
    ema_fast, ema_slow = float(last["ema_fast"]), float(last["ema_slow"])
    return Indicators(rsi, ema_fast, ema_slow, "up" if ema_fast > ema_slow else "down")


def _against_trend(side: str, indicators: Indicators) -> bool:
    return (side == "long") != (indicators.trend == "up")


def order_tips(
    db: Session, player: Player, position: Position, indicators: Indicators | None, value_before: float, now_ms: int
) -> list[dict]:
    """Micro lessons for a just-opened position; each one at most once per UTC day per player."""
    rsi = indicators.rsi if indicators is not None else None
    rules = {
        "overbought_buy": position.side == "long" and rsi is not None and rsi > 70,
        "oversold_short": position.side == "short" and rsi is not None and rsi < 30,
        "against_trend": indicators is not None and _against_trend(position.side, indicators),
        "no_stop": position.stop_loss is None,
        "big_position": position.reserved > BIG_POSITION_SHARE * value_before,
    }
    tips = []
    for code, lesson_id in TIP_LESSONS.items():
        if len(tips) == MAX_TIPS_PER_ORDER:
            break
        if rules[code] and log_event(db, player, f"tip_{code}", now_ms, once_per_day=True):
            tips.append({"code": code, "lesson_id": lesson_id})
    return tips


def _ai_at_entry(db: Session, viewer: Player, position: Position, now_ms: int) -> list[dict]:
    """Each AI's latest opinion on the pair before the entry, hidden from free players for an hour."""
    if position.symbol not in AI_SYMBOLS:
        return []
    visible_until = position.opened_at
    if not is_pro(viewer, now_ms):
        visible_until = min(visible_until, now_ms - AI_VISIBILITY_DELAY_MS)
    rows = []
    for ai in db.query(Player).filter_by(is_ai=True).order_by(Player.id):
        decision = (
            db.query(AiDecision)
            .filter(
                AiDecision.player_id == ai.id,
                AiDecision.symbol == position.symbol,
                AiDecision.created_at <= visible_until,
                AiDecision.created_at > position.opened_at - INSIGHT_MAX_AGE_MS,
            )
            .order_by(AiDecision.created_at.desc(), AiDecision.id.desc())
            .first()
        )
        if decision is not None:
            rows.append({"nickname": ai.nickname, "view": decision.view, "probability_up": decision.probability_up})
    return rows


def _notes(position: Position, entry: Indicators | None, ai: list[dict]) -> list[str]:
    notes = []
    if entry is not None:
        if position.side == "long" and entry.rsi is not None and entry.rsi > 70:
            notes.append("entry_overbought")
        if position.side == "short" and entry.rsi is not None and entry.rsi < 30:
            notes.append("entry_oversold")
        notes.append("against_trend" if _against_trend(position.side, entry) else "with_trend")
    reason_notes = {"stop_loss": "stopped_out", "take_profit": "took_profit", "season_end": "season_end"}
    if position.close_reason in reason_notes:
        notes.append(reason_notes[position.close_reason])
    if position.pnl < 0 and position.stop_loss is None:
        notes.append("no_stop_loss")
    bullish = sum(row["view"] == "bullish" for row in ai)
    bearish = sum(row["view"] == "bearish" for row in ai)
    if bullish != bearish:
        majority_long = bullish > bearish
        notes.append("with_ai" if majority_long == (position.side == "long") else "against_ai")
    return notes


def trade_review(db: Session, viewer: Player, position: Position, now_ms: int) -> dict:
    """Template review of a closed position: result, indicators at entry and exit, AI opinions."""
    entry = indicators_at(db, position.symbol, position.opened_at)
    exit_ = indicators_at(db, position.symbol, position.closed_at)
    ai = _ai_at_entry(db, viewer, position, now_ms)
    return {
        "position_id": position.id,
        "symbol": position.symbol,
        "side": position.side,
        "result": {
            "entry_price": position.entry_price,
            "exit_price": position.exit_price,
            "pnl": position.pnl,
            "pnl_pct": position.pnl / position.reserved * 100,
            "duration_ms": position.closed_at - position.opened_at,
            "close_reason": position.close_reason,
        },
        "entry": asdict(entry) if entry is not None else None,
        "exit": asdict(exit_) if exit_ is not None else None,
        "ai": ai,
        "notes": _notes(position, entry, ai),
    }
