"""Daily chart puzzle: a historical moment scored by its setup (trend + RSI)."""
from __future__ import annotations

import random

import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.models import Candle
from app.game.analytics import log_event
from app.game.channel import day_key
from app.game.config import (
    CHART_TIMEFRAME,
    DAY_MS,
    PUZZLE_AFTER_CANDLES,
    PUZZLE_CHART_CANDLES,
    PUZZLE_LOOKBACK_MS,
    PUZZLE_MIN_AGE_MS,
    PUZZLE_MIN_EMA_GAP,
    PUZZLE_TRIES,
    STARTER_SYMBOLS,
    XP_PER_PUZZLE,
)
from app.game.errors import PuzzleAnswered
from app.game.insights import CANDLE_HISTORY, CANDLE_MS, WHY_LESSONS, Indicators, indicators_at
from app.game.models import DailyPuzzle, Player, PuzzleAnswer
from app.game.progress import award_xp
from app.services.indicator_service import IndicatorService


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


def _candle_json(row: Candle) -> dict:
    return {"time": row.timestamp // 1000, "open": row.open, "high": row.high, "low": row.low, "close": row.close}


def _candles(db: Session, puzzle: DailyPuzzle):
    return db.query(Candle).filter(Candle.symbol == puzzle.symbol, Candle.timeframe == CHART_TIMEFRAME)


def puzzle_chart(db: Session, puzzle: DailyPuzzle) -> dict:
    """The chart up to the moment: 60 candles and both EMAs (warmed up on 100 candles)."""
    rows = (
        _candles(db, puzzle)
        .filter(Candle.timestamp <= puzzle.ts - CANDLE_MS)
        .order_by(Candle.timestamp.desc())
        .limit(CANDLE_HISTORY)
        .all()
    )[::-1]
    tail = rows[-PUZZLE_CHART_CANDLES:]
    chart = {"candles": [_candle_json(row) for row in tail], "ema_fast": [], "ema_slow": []}
    if not rows:
        return chart
    frame = IndicatorService(db).calculate_indicators(pd.DataFrame({"close": [row.close for row in rows]}, dtype=float))
    for key in ("ema_fast", "ema_slow"):
        values = frame[key].iloc[-PUZZLE_CHART_CANDLES:]
        chart[key] = [{"time": row.timestamp // 1000, "value": float(value)} for row, value in zip(tail, values)]
    return chart


def answer_puzzle(db: Session, player: Player, puzzle: DailyPuzzle, choice: str, now_ms: int) -> PuzzleAnswer:
    """Record the player's one answer for the day; XP only for the setup's call."""
    if db.query(PuzzleAnswer.id).filter_by(player_id=player.id, day=puzzle.day).first() is not None:
        raise PuzzleAnswered(puzzle.day)
    answer = PuzzleAnswer(
        player_id=player.id, day=puzzle.day, choice=choice, correct=choice == puzzle.answer, answered_at=now_ms
    )
    try:
        # Savepoint: a parallel request may have recorded the same answer first.
        with db.begin_nested():
            db.add(answer)
    except IntegrityError:
        raise PuzzleAnswered(puzzle.day)
    if answer.correct:
        award_xp(player, XP_PER_PUZZLE)
    log_event(db, player, "puzzle_done", now_ms)
    return answer


def puzzle_result(db: Session, puzzle: DailyPuzzle, answer: PuzzleAnswer) -> dict:
    """The reveal: the answer, the next hour of candles, the why and how others answered."""
    after = (
        _candles(db, puzzle)
        .filter(Candle.timestamp >= puzzle.ts)
        .order_by(Candle.timestamp)
        .limit(PUZZLE_AFTER_CANDLES)
        .all()
    )
    moment = _candles(db, puzzle).filter(Candle.timestamp == puzzle.ts - CANDLE_MS).one_or_none()
    outcome_pct = None
    if moment is not None and len(after) == PUZZLE_AFTER_CANDLES:
        outcome_pct = (after[-1].close / moment.close - 1) * 100
    answers = db.query(PuzzleAnswer).filter_by(day=puzzle.day).all()
    total = len(answers) or 1
    return {
        "choice": answer.choice,
        "answer": puzzle.answer,
        "correct": answer.correct,
        "xp": XP_PER_PUZZLE if answer.correct else 0,
        "after": [_candle_json(row) for row in after],
        "outcome_pct": outcome_pct,
        "steps": puzzle_steps(puzzle),
        "rsi": puzzle.rsi,
        "trend": "up" if puzzle.ema_fast > puzzle.ema_slow else "down",
        "same_pct": round(100 * sum(row.choice == answer.choice for row in answers) / total),
        "correct_pct": round(100 * sum(row.correct for row in answers) / total),
    }
