"""Replay trainer: a random past week, revealed candle by candle in the Mini App."""
from __future__ import annotations

import random

from sqlalchemy.orm import Session

from app.core.db.models import Candle
from app.game.analytics import log_event
from app.game.config import (
    AI_SYMBOLS,
    CANDLE_TIMEFRAME,
    CANDLE_TIMEFRAME_MS,
    REPLAY_CANDLES,
    REPLAY_GROUP,
    REPLAY_LOOKBACK_MS,
    REPLAY_SHOW,
    SCENARIO_MAX_LOSS_PCT,
    SCENARIO_TOP,
    XP_PER_REPLAY,
    XP_PER_SCENARIO,
)
from app.game.models import Player
from app.game.progress import award_xp
from app.game.puzzle import FAKE_EPOCH_S

TRIES = 20


def _hour(rows: list[Candle], start: int) -> dict:
    group = rows[start : start + REPLAY_GROUP]
    return {
        "open": group[0].open,
        "high": max(row.high for row in group),
        "low": min(row.low for row in group),
        "close": group[-1].close,
    }


def _rows(db: Session, symbol: str, now_ms: int) -> list[Candle]:
    return (
        db.query(Candle)
        .filter(
            Candle.symbol == symbol,
            Candle.timeframe == CANDLE_TIMEFRAME,
            Candle.timestamp >= now_ms - REPLAY_LOOKBACK_MS,
            Candle.timestamp < now_ms,
        )
        .order_by(Candle.timestamp)
        .all()
    )


SIZE = REPLAY_CANDLES * REPLAY_GROUP


def _gap_free(rows: list[Candle], start: int) -> bool:
    return rows[start + SIZE - 1].timestamp - rows[start].timestamp == (SIZE - 1) * CANDLE_TIMEFRAME_MS


def _week(rows: list[Candle], start: int) -> list[dict]:
    return [{"time": FAKE_EPOCH_S + i * 3600, **_hour(rows, start + i * REPLAY_GROUP)} for i in range(REPLAY_CANDLES)]


def replay_view(db: Session, now_ms: int, rng: random.Random | None = None) -> dict | None:
    """A gap-free week of one AI pair as 1h candles with fake times; None if history is too short."""
    rng = rng or random.Random()
    symbol = rng.choice(AI_SYMBOLS)
    rows = _rows(db, symbol, now_ms)
    if len(rows) < SIZE:
        return None
    for _ in range(TRIES):
        start = rng.randrange(len(rows) - SIZE + 1)
        if _gap_free(rows, start):
            return {"symbol": symbol, "show": REPLAY_SHOW, "xp": XP_PER_REPLAY, "candles": _week(rows, start)}
    return None


def scenario_score(kind: str, candles: list[dict]) -> float:
    """How well the revealed part of a week fits the episode; higher is better."""
    base = candles[REPLAY_SHOW - 1]["close"]
    shown = candles[REPLAY_SHOW:]
    high = max(c["high"] for c in shown)
    low = min(c["low"] for c in shown)
    end = shown[-1]["close"]
    if kind == "crash":
        return (base - end) / base
    if kind == "pump_dump":  # needs both legs: the rise and the fall back from the peak
        return min(high - base, high - end) / base
    return -(high - low) / base  # flat


def scenario_view(db: Session, now_ms: int, kind: str, rng: random.Random | None = None) -> dict | None:
    """A week of an AI pair that best fits the episode kind, random among the top few; None without history."""
    rng = rng or random.Random()
    weeks = []
    for symbol in AI_SYMBOLS:
        rows = _rows(db, symbol, now_ms)
        # Hour-aligned starts: every week is a slice of one list of hours.
        hours = [_hour(rows, i) for i in range(0, len(rows) - REPLAY_GROUP + 1, REPLAY_GROUP)]
        for k, start in enumerate(range(0, len(rows) - SIZE + 1, REPLAY_GROUP)):
            if _gap_free(rows, start):
                candles = [{"time": FAKE_EPOCH_S + i * 3600, **hour} for i, hour in enumerate(hours[k : k + REPLAY_CANDLES])]
                weeks.append((scenario_score(kind, candles), symbol, candles))
    if not weeks:
        return None
    weeks.sort(key=lambda week: week[0], reverse=True)
    _, symbol, candles = rng.choice(weeks[:SCENARIO_TOP])
    return {
        "kind": kind,
        "symbol": symbol,
        "show": REPLAY_SHOW,
        "xp": XP_PER_SCENARIO,
        "max_loss": SCENARIO_MAX_LOSS_PCT,
        "candles": candles,
    }


def finish_replay(db: Session, player: Player, now_ms: int) -> int:
    """XP for the first finished replay of the UTC day; counts for the streak.
    shortcut: the client has the whole week, so XP is for finishing, not for PnL; grade PnL server-side if it pays out."""
    if not log_event(db, player, "replay_done", now_ms, once_per_day=True):
        return 0
    award_xp(player, XP_PER_REPLAY)
    return XP_PER_REPLAY


def finish_scenario(db: Session, player: Player, passed: bool, now_ms: int) -> int:
    """XP for the first passed scenario of the UTC day; counts for the streak.
    shortcut: pass/fail is reported by the client, which has the whole week; check trades server-side if XP grows."""
    if not passed or not log_event(db, player, "scenario_done", now_ms, once_per_day=True):
        return 0
    award_xp(player, XP_PER_SCENARIO)
    return XP_PER_SCENARIO
