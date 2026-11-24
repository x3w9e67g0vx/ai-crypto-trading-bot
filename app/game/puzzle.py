"""Daily chart puzzle: a historical window, guess long/short/skip, then see what came next."""
from __future__ import annotations

import random

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.models import Candle
from app.game.analytics import log_event
from app.game.channel import day_key
from app.game.config import (
    AI_SYMBOLS,
    CANDLE_TIMEFRAME,
    CANDLE_TIMEFRAME_MS,
    PUZZLE_FLAT_PCT,
    PUZZLE_HORIZON,
    PUZZLE_LOOKBACK_MS,
    PUZZLE_MIN_AGE_MS,
    PUZZLE_MOVE_PCT,
    PUZZLE_SHOW,
    XP_PER_PUZZLE,
)
from app.game.errors import PuzzleNotFound
from app.game.insights import indicators_at
from app.game.models import DailyPuzzle, Player, PuzzleAnswer
from app.game.progress import award_xp

CHOICES = ("long", "short", "skip")
TRIES = 50
FLAT_SHARE = 0.25
# Chart times are shown from this fake epoch so the window can't be looked up by date.
FAKE_EPOCH_S = 1_600_000_000


def _answer_for(move_pct: float, want_flat: bool) -> str | None:
    if want_flat:
        return "skip" if abs(move_pct) < PUZZLE_FLAT_PCT else None
    if abs(move_pct) >= PUZZLE_MOVE_PCT:
        return "long" if move_pct > 0 else "short"
    return None


def _pick(db: Session, day: str, now_ms: int) -> DailyPuzzle | None:
    rng = random.Random(day)
    series: dict[str, list[Candle]] = {}
    for symbol in AI_SYMBOLS:
        series[symbol] = (
            db.query(Candle)
            .filter(
                Candle.symbol == symbol,
                Candle.timeframe == CANDLE_TIMEFRAME,
                Candle.timestamp >= now_ms - PUZZLE_LOOKBACK_MS,
                Candle.timestamp < now_ms - PUZZLE_MIN_AGE_MS,
            )
            .order_by(Candle.timestamp)
            .all()
        )
    # A flat day falls back to a move if no flat window turns up.
    modes = (True, False) if rng.random() < FLAT_SHARE else (False,)
    for want_flat in modes:
        for _ in range(TRIES):
            symbol = rng.choice(AI_SYMBOLS)
            rows = series[symbol]
            if len(rows) < PUZZLE_SHOW + PUZZLE_HORIZON:
                continue
            cut = rng.randrange(PUZZLE_SHOW - 1, len(rows) - PUZZLE_HORIZON)
            first, last = rows[cut - PUZZLE_SHOW + 1], rows[cut + PUZZLE_HORIZON]
            # Skip windows with gaps in the stored candles.
            if last.timestamp - first.timestamp != (PUZZLE_SHOW + PUZZLE_HORIZON - 1) * CANDLE_TIMEFRAME_MS:
                continue
            move_pct = (last.close / rows[cut].close - 1) * 100
            answer = _answer_for(move_pct, want_flat)
            if answer is not None:
                return DailyPuzzle(
                    day=day,
                    symbol=symbol,
                    cut_ts=rows[cut].timestamp,
                    answer=answer,
                    move_pct=move_pct,
                    created_at=now_ms,
                )
    return None


def todays_puzzle(db: Session, now_ms: int) -> DailyPuzzle | None:
    """The puzzle of the current UTC day, picked on first request; None if history is too short."""
    day = day_key(now_ms)
    puzzle = db.get(DailyPuzzle, day)
    if puzzle is not None:
        return puzzle
    puzzle = _pick(db, day, now_ms)
    if puzzle is None:
        return None
    try:
        # Savepoint: a parallel request may have stored today's puzzle first.
        with db.begin_nested():
            db.add(puzzle)
    except IntegrityError:
        return db.get(DailyPuzzle, day)
    return puzzle


def _candles(db: Session, puzzle: DailyPuzzle, start_ts: int, end_ts: int) -> list[dict]:
    rows = (
        db.query(Candle)
        .filter(
            Candle.symbol == puzzle.symbol,
            Candle.timeframe == CANDLE_TIMEFRAME,
            Candle.timestamp >= start_ts,
            Candle.timestamp <= end_ts,
        )
        .order_by(Candle.timestamp)
        .all()
    )
    return [
        {
            "time": FAKE_EPOCH_S + (row.timestamp - puzzle.cut_ts) // 1000,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
        }
        for row in rows
    ]


def _result(db: Session, puzzle: DailyPuzzle, answer: PuzzleAnswer) -> dict:
    step = CANDLE_TIMEFRAME_MS
    indicators = indicators_at(db, puzzle.symbol, puzzle.cut_ts + step)
    rsi = indicators.rsi if indicators else None
    return {
        "choice": answer.choice,
        "correct": answer.correct,
        "answer": puzzle.answer,
        "symbol": puzzle.symbol,
        "move_pct": puzzle.move_pct,
        "trend": indicators.trend if indicators else None,
        "rsi": rsi,
        # RSI at an extreme explains more than the trend; otherwise point to the trend lesson.
        "lesson_id": "07" if rsi is not None and (rsi >= 70 or rsi <= 30) else "06",
        "after": _candles(db, puzzle, puzzle.cut_ts + step, puzzle.cut_ts + PUZZLE_HORIZON * step),
    }


def puzzle_view(db: Session, player: Player, now_ms: int) -> dict | None:
    """What the Mini App shows: the window, plus the outcome once the player has answered."""
    puzzle = todays_puzzle(db, now_ms)
    if puzzle is None:
        return None
    answer = db.query(PuzzleAnswer).filter_by(player_id=player.id, day=puzzle.day).one_or_none()
    return {
        "day": puzzle.day,
        "xp": XP_PER_PUZZLE,
        "candles": _candles(db, puzzle, puzzle.cut_ts - (PUZZLE_SHOW - 1) * CANDLE_TIMEFRAME_MS, puzzle.cut_ts),
        "result": _result(db, puzzle, answer) if answer else None,
    }


def answer_puzzle(db: Session, player: Player, choice: str, now_ms: int) -> int:
    """Record the player's one answer for today; returns XP granted (0 if wrong or already answered)."""
    if choice not in CHOICES:
        raise ValueError(choice)
    puzzle = todays_puzzle(db, now_ms)
    if puzzle is None:
        raise PuzzleNotFound(day_key(now_ms))
    correct = choice == puzzle.answer
    try:
        with db.begin_nested():
            db.add(PuzzleAnswer(player_id=player.id, day=puzzle.day, choice=choice, correct=correct, created_at=now_ms))
    except IntegrityError:
        return 0
    log_event(db, player, "puzzle_done", now_ms)
    if not correct:
        return 0
    award_xp(player, XP_PER_PUZZLE)
    return XP_PER_PUZZLE
