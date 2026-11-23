import pytest

from app.game.config import HOUR_MS, PUZZLE_LOOKBACK_MS, PUZZLE_MIN_AGE_MS, STARTER_SYMBOLS
from app.game.insights import CANDLE_MS, Indicators, indicators_at
from app.game.models import DailyPuzzle
from app.game.puzzle import daily_puzzle, puzzle_steps, setup_answer
from tests.game.conftest import NOW
from tests.game.test_insights import add_candles

DAY_START = NOW - NOW % (24 * HOUR_MS)


@pytest.mark.parametrize(
    "rsi, fast, slow, trend, answer",
    [
        (55, 101, 100, "up", "long"),
        (75, 101, 100, "up", "skip"),
        (45, 99, 100, "down", "short"),
        (25, 99, 100, "down", "skip"),
        (55, 100.1, 100, "up", None),  # gap 0.1%
        (None, 101, 100, "up", None),
    ],
)
def test_setup_answer_rules(rsi, fast, slow, trend, answer):
    assert setup_answer(Indicators(rsi, fast, slow, trend)) == answer


def test_no_candles_no_puzzle(db):
    assert daily_puzzle(db, NOW) is None
    assert db.query(DailyPuzzle).count() == 0


@pytest.fixture
def candles(db):
    for i, symbol in enumerate(STARTER_SYMBOLS):
        add_candles(db, rising=i % 2 == 0, count=30 * 288, end_ms=NOW, symbol=symbol)


def test_daily_puzzle_picks_valid_moment(db, candles):
    puzzle = daily_puzzle(db, NOW)
    assert puzzle is not None
    assert puzzle.symbol in STARTER_SYMBOLS
    assert puzzle.ts % CANDLE_MS == 0
    assert DAY_START - PUZZLE_LOOKBACK_MS <= puzzle.ts <= DAY_START - PUZZLE_MIN_AGE_MS
    assert puzzle.answer == setup_answer(indicators_at(db, puzzle.symbol, puzzle.ts))


def test_daily_puzzle_reuses_row(db, candles):
    first = daily_puzzle(db, NOW)
    second = daily_puzzle(db, NOW + HOUR_MS)
    assert second.ts == first.ts
    assert db.query(DailyPuzzle).count() == 1


def test_daily_puzzle_same_day_same_moment(db, candles):
    first = daily_puzzle(db, NOW)
    picked = (first.symbol, first.ts)
    db.delete(first)
    db.flush()
    again = daily_puzzle(db, NOW + 3 * HOUR_MS)
    assert (again.symbol, again.ts) == picked


@pytest.mark.parametrize("rsi, code", [(75, "rsi_overbought"), (25, "rsi_oversold"), (50, "rsi_neutral")])
def test_puzzle_steps_codes(rsi, code):
    puzzle = DailyPuzzle(day="2026-10-28", symbol="BTC/USDT", ts=NOW, answer="long", rsi=rsi, ema_fast=101, ema_slow=100)
    steps = puzzle_steps(puzzle)
    assert [step["code"] for step in steps] == ["trend", code]
    assert [step["lesson_id"] for step in steps] == ["06", "07"]
