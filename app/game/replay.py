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
    XP_PER_REPLAY,
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


def replay_view(db: Session, now_ms: int, rng: random.Random | None = None) -> dict | None:
    """A gap-free week of one AI pair as 1h candles with fake times; None if history is too short."""
    rng = rng or random.Random()
    symbol = rng.choice(AI_SYMBOLS)
    rows = (
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
    size = REPLAY_CANDLES * REPLAY_GROUP
    if len(rows) < size:
        return None
    for _ in range(TRIES):
        start = rng.randrange(len(rows) - size + 1)
        if rows[start + size - 1].timestamp - rows[start].timestamp != (size - 1) * CANDLE_TIMEFRAME_MS:
            continue
        candles = [
            {"time": FAKE_EPOCH_S + i * 3600, **_hour(rows, start + i * REPLAY_GROUP)} for i in range(REPLAY_CANDLES)
        ]
        return {"symbol": symbol, "show": REPLAY_SHOW, "xp": XP_PER_REPLAY, "candles": candles}
    return None


def finish_replay(db: Session, player: Player, now_ms: int) -> int:
    """XP for the first finished replay of the UTC day; counts for the streak.
    shortcut: the client has the whole week, so XP is for finishing, not for PnL; grade PnL server-side if it pays out."""
    if not log_event(db, player, "replay_done", now_ms, once_per_day=True):
        return 0
    award_xp(player, XP_PER_REPLAY)
    return XP_PER_REPLAY
