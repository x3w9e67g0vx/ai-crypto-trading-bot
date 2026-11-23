import pytest

from app.core.db.models import Candle
from app.game.channel import day_key
from app.game.config import HOUR_MS, PUZZLE_LOOKBACK_MS, PUZZLE_MIN_AGE_MS, STARTER_SYMBOLS, XP_PER_PUZZLE
from app.game.errors import PuzzleAnswered
from app.game.insights import CANDLE_MS, Indicators, indicators_at
from app.game.models import DailyPuzzle, Event
from app.game.puzzle import (
    answer_puzzle,
    daily_puzzle,
    puzzle_chart,
    puzzle_result,
    puzzle_steps,
    setup_answer,
)
from tests.game.conftest import NOW, make_player
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


PUZZLE_TS = DAY_START - 3 * HOUR_MS


@pytest.fixture
def puzzle(db):
    """A fixed puzzle with 200 rising candles: 188 up to the moment, 12 after it."""
    add_candles(db, count=200, end_ms=PUZZLE_TS + 12 * CANDLE_MS)
    indicators = indicators_at(db, "BTC/USDT", PUZZLE_TS)
    row = DailyPuzzle(
        day=day_key(NOW), symbol="BTC/USDT", ts=PUZZLE_TS, answer=setup_answer(indicators), rsi=indicators.rsi,
        ema_fast=indicators.ema_fast, ema_slow=indicators.ema_slow, created_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _wrong(answer):
    return next(choice for choice in ("long", "short", "skip") if choice != answer)


def test_answer_correct_awards_xp(db, puzzle):
    player = make_player(db, telegram_id=1)
    answer = answer_puzzle(db, player, puzzle, puzzle.answer, NOW)
    assert answer.correct is True
    assert player.xp == XP_PER_PUZZLE
    assert db.query(Event).filter_by(player_id=player.id, kind="puzzle_done").count() == 1


def test_answer_wrong_no_xp(db, puzzle):
    player = make_player(db, telegram_id=1)
    answer = answer_puzzle(db, player, puzzle, _wrong(puzzle.answer), NOW)
    assert answer.correct is False
    assert not player.xp
    assert puzzle_result(db, puzzle, answer)["xp"] == 0


def test_answer_twice_raises(db, puzzle):
    player = make_player(db, telegram_id=1)
    answer_puzzle(db, player, puzzle, puzzle.answer, NOW)
    with pytest.raises(PuzzleAnswered):
        answer_puzzle(db, player, puzzle, puzzle.answer, NOW)
    assert player.xp == XP_PER_PUZZLE


def test_result_after_and_outcome(db, puzzle):
    player = make_player(db, telegram_id=1)
    result = puzzle_result(db, puzzle, answer_puzzle(db, player, puzzle, puzzle.answer, NOW))
    after = result["after"]
    assert len(after) == 12
    assert after[0]["time"] * 1000 == puzzle.ts
    closes = {row.timestamp: row.close for row in db.query(Candle)}
    expected = (closes[puzzle.ts + 11 * CANDLE_MS] / closes[puzzle.ts - CANDLE_MS] - 1) * 100
    assert result["outcome_pct"] == pytest.approx(expected)
    assert result["steps"] == puzzle_steps(puzzle)
    assert result["trend"] == "up"


def test_chart_ends_at_moment(db, puzzle):
    chart = puzzle_chart(db, puzzle)
    assert [len(chart[key]) for key in ("candles", "ema_fast", "ema_slow")] == [60, 60, 60]
    assert chart["candles"][-1]["time"] * 1000 == puzzle.ts - CANDLE_MS
    assert chart["ema_fast"][-1]["time"] == chart["candles"][-1]["time"]
    assert chart["ema_fast"][-1]["value"] == pytest.approx(puzzle.ema_fast)


def test_community_pcts(db):
    db.add(DailyPuzzle(day=day_key(NOW), symbol="BTC/USDT", ts=PUZZLE_TS, answer="long", rsi=55,
                       ema_fast=101, ema_slow=100, created_at=NOW))
    db.flush()
    puzzle = db.get(DailyPuzzle, day_key(NOW))
    players = [make_player(db, telegram_id=i) for i in (1, 2, 3)]
    answers = [answer_puzzle(db, p, puzzle, choice, NOW) for p, choice in zip(players, ("long", "long", "skip"))]
    result = puzzle_result(db, puzzle, answers[0])
    assert result["same_pct"] == 67
    assert result["correct_pct"] == 67
    assert result["outcome_pct"] is None  # no candles
