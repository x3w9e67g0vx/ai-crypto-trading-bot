"""Daily chart puzzle: a historical moment scored by its setup (trend + RSI)."""
from __future__ import annotations

import random

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.models import Candle
from app.game.channel import day_key
from app.game.config import (
    CHART_TIMEFRAME,
    DAY_MS,
    PUZZLE_AFTER_CANDLES,
    PUZZLE_LOOKBACK_MS,
    PUZZLE_MIN_AGE_MS,
    PUZZLE_MIN_EMA_GAP,
    PUZZLE_TRIES,
    STARTER_SYMBOLS,
)
from app.game.insights import CANDLE_MS, WHY_LESSONS, Indicators, indicators_at
from app.game.models import DailyPuzzle


def setup_answer(indicators: Indicators) -> str | None:
    """The right call for a setup; None when the trend is too weak or RSI is undefined."""
    gap = abs(indicators.ema_fast - indicators.ema_slow) / indicators.ema_slow
    if gap < PUZZLE_MIN_EMA_GAP or indicators.rsi is None:
        return None
    if indicators.trend == "up":
        return "skip" if indicators.rsi > 70 else "long"
    return "skip" if indicators.rsi < 30 else "short"


def _has_candle(db: Session, symbol: str, ts_ms: int) -> bool:
    query = db.query(Candle.id).filter_by(symbol=symbol, timeframe=CHART_TIMEFRAME, timestamp=ts_ms)
    return db.query(query.exists()).scalar()


def daily_puzzle(db: Session, now_ms: int) -> DailyPuzzle | None:
    """Today's puzzle, picked on first request; None if no valid moment was found."""
    day = day_key(now_ms)
    puzzle = db.get(DailyPuzzle, day)
    if puzzle is not None:
        return puzzle
    # Seeded by the day so every request on the same day tries the same moments.
    rng = random.Random(day)
    symbol = rng.choice(STARTER_SYMBOLS)
    day_start = now_ms - now_ms % DAY_MS
    start, end = day_start - PUZZLE_LOOKBACK_MS, day_start - PUZZLE_MIN_AGE_MS
    for _ in range(PUZZLE_TRIES):
        ts = start + rng.randrange((end - start) // CANDLE_MS) * CANDLE_MS
        if not _has_candle(db, symbol, ts + (PUZZLE_AFTER_CANDLES - 1) * CANDLE_MS):
            continue
        indicators = indicators_at(db, symbol, ts)
        answer = setup_answer(indicators) if indicators is not None else None
        if answer is None:
            continue
        puzzle = DailyPuzzle(
            day=day, symbol=symbol, ts=ts, answer=answer, rsi=indicators.rsi,
            ema_fast=indicators.ema_fast, ema_slow=indicators.ema_slow, created_at=now_ms,
        )
        try:
            # Savepoint: a parallel request may have picked today's puzzle first.
            with db.begin_nested():
                db.add(puzzle)
        except IntegrityError:
            return db.get(DailyPuzzle, day)
        return puzzle
    return None


def puzzle_steps(puzzle: DailyPuzzle) -> list[dict]:
    """Why the answer is right: the trend, then where RSI stood."""
    rsi = puzzle.rsi
    rsi_code = "rsi_overbought" if rsi > 70 else "rsi_oversold" if rsi < 30 else "rsi_neutral"
    return [{"code": code, "lesson_id": WHY_LESSONS[code]} for code in ("trend", rsi_code)]
