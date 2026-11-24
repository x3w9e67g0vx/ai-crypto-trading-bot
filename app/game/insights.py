"""Micro lessons on orders and template reviews of closed trades."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd
from sqlalchemy.orm import Session

from app.core.db.models import Candle
from app.game.ai_personas import PERSONAS
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
from app.game.models import AiDecision, Player, Portfolio, Position
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


RISKY_NOTES = {"entry_overbought", "entry_oversold", "against_trend"}


def _grade(position: Position, notes: list[str]) -> str:
    """Process over outcome: a clean loss is discipline, a sloppy win is luck."""
    if position.stop_loss is not None and not RISKY_NOTES & set(notes):
        return "discipline"
    return "luck" if position.pnl > 0 else "risk"


def trade_review(db: Session, viewer: Player, position: Position, now_ms: int) -> dict:
    """Template review of a closed position: result, indicators at entry and exit, AI opinions."""
    entry = indicators_at(db, position.symbol, position.opened_at)
    exit_ = indicators_at(db, position.symbol, position.closed_at)
    ai = _ai_at_entry(db, viewer, position, now_ms)
    notes = _notes(position, entry, ai)
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
        "notes": notes,
        "grade": _grade(position, notes),
    }


# Step of an AI entry -> lesson that explains it.
WHY_LESSONS = {
    "signal": "10",
    "trend": "06",
    "no_trend_filter": "06",
    "rsi_overbought": "07",
    "rsi_oversold": "07",
    "rsi_neutral": "07",
    "size": "03",
    "stops": "04",
}


def ai_entry_why(db: Session, viewer: Player, position_id: int, now_ms: int) -> dict | None:
    """Why an AI opened a position, step by step as it decided; None if it is not
    an AI position or the viewer may not see it yet (same delay as the AI profile)."""
    row = (
        db.query(Position, Player)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .join(Player, Portfolio.player_id == Player.id)
        .filter(Position.id == position_id, Player.is_ai.is_(True))
        .one_or_none()
    )
    if row is None:
        return None
    position, ai = row
    if not is_pro(viewer, now_ms) and position.opened_at > now_ms - AI_VISIBILITY_DELAY_MS:
        return None

    persona = next(p for p in PERSONAS if p.key == ai.ai_key)
    # The AI opens in the same turn it decides, so the decision shares the timestamp.
    decision = (
        db.query(AiDecision)
        .filter_by(player_id=ai.id, symbol=position.symbol, created_at=position.opened_at)
        .one_or_none()
    )
    long = position.side == "long"
    snapshot = decision is not None and decision.buy_threshold is not None
    if long:
        threshold = decision.buy_threshold if snapshot else persona.buy_threshold
    else:
        threshold = decision.sell_threshold if snapshot else persona.sell_threshold
    trend_filter = decision.trend_filter if snapshot else persona.use_trend_filter
    entry = indicators_at(db, position.symbol, position.opened_at)
    if decision is not None and decision.ema_fast is not None and decision.ema_slow is not None:
        trend = "up" if decision.ema_fast > decision.ema_slow else "down"
    else:
        trend = entry.trend if entry is not None else None
    rsi = entry.rsi if entry is not None else None

    steps = ["signal"] if decision is not None else []
    steps.append("trend" if trend_filter else "no_trend_filter")
    if rsi is not None:
        steps.append("rsi_overbought" if rsi > 70 else "rsi_oversold" if rsi < 30 else "rsi_neutral")
    steps += ["size", "stops"]

    def pct_from_entry(price: float | None) -> float | None:
        return None if price is None else (price / position.entry_price - 1) * 100

    return {
        "position_id": position.id,
        "nickname": ai.nickname,
        "persona": persona.key,
        "symbol": position.symbol,
        "side": position.side,
        "opened_at": position.opened_at,
        "entry_price": position.entry_price,
        "amount_usdt": position.reserved,
        "stop_loss": position.stop_loss,
        "take_profit": position.take_profit,
        "stop_pct": pct_from_entry(position.stop_loss),
        "take_pct": pct_from_entry(position.take_profit),
        "probability_up": decision.probability_up if decision is not None else None,
        "threshold": threshold,
        "trend_filter": trend_filter,
        "trend": trend,
        "rsi": rsi,
        "steps": [{"code": code, "lesson_id": WHY_LESSONS[code]} for code in steps],
    }
