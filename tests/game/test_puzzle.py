import pytest

from app.core.db.models import Candle
from app.game.config import CANDLE_TIMEFRAME_MS, DAY_MS, PUZZLE_HORIZON, PUZZLE_MIN_AGE_MS, PUZZLE_SHOW, XP_PER_PUZZLE
from app.game.models import DailyPuzzle, Event, PuzzleAnswer
from app.game.puzzle import FAKE_EPOCH_S, answer_puzzle, puzzle_view, todays_puzzle
from tests.game.conftest import NOW, make_player

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def add_candles(db, *, step_pct=0.1, days=3, symbols=SYMBOLS, skip=()):
    """Candles ending just before the puzzle's min age; each close is step_pct above the previous."""
    end = NOW - PUZZLE_MIN_AGE_MS
    end -= end % CANDLE_TIMEFRAME_MS
    count = days * DAY_MS // CANDLE_TIMEFRAME_MS
    for symbol in symbols:
        price = 100.0
        for i in range(count):
            ts = end - (count - i) * CANDLE_TIMEFRAME_MS
            new = price * (1 + step_pct / 100)
            if i not in skip:
                db.add(Candle(symbol=symbol, timeframe="5m", timestamp=ts, open=price, high=max(price, new),
                              low=min(price, new), close=new, volume=1.0, source="binance"))
            price = new
    db.flush()


def test_no_history_no_puzzle(db):
    player = make_player(db)
    assert todays_puzzle(db, NOW) is None
    assert puzzle_view(db, player, NOW) is None


def test_puzzle_is_picked_once_per_day(db):
    add_candles(db)
    puzzle = todays_puzzle(db, NOW)
    assert puzzle.day == "2026-10-28"
    assert puzzle.answer == "long"  # steady rise: 12 candles x 0.1% > 0.5%
    assert puzzle.move_pct == pytest.approx((1.001**PUZZLE_HORIZON - 1) * 100)
    assert puzzle.cut_ts < NOW - PUZZLE_MIN_AGE_MS
    assert todays_puzzle(db, NOW + 3600_000) is puzzle
    assert db.query(DailyPuzzle).count() == 1


def test_flat_market_gives_skip_or_nothing(db):
    add_candles(db, step_pct=0.0)
    puzzle = todays_puzzle(db, NOW)
    # A move day finds no window in a flat market; a flat day answers "skip".
    assert puzzle is None or puzzle.answer == "skip"


def test_gaps_are_skipped(db):
    count = 3 * DAY_MS // CANDLE_TIMEFRAME_MS
    # Every 50th candle missing: no gap-free 72-candle window exists.
    add_candles(db, skip=set(range(0, count, 50)))
    assert todays_puzzle(db, NOW) is None


def test_view_hides_outcome_until_answered(db):
    add_candles(db)
    player = make_player(db)
    view = puzzle_view(db, player, NOW)
    assert view["result"] is None
    assert len(view["candles"]) == PUZZLE_SHOW
    assert view["candles"][-1]["time"] == FAKE_EPOCH_S
    assert "symbol" not in view


def test_correct_answer_gives_xp_once(db):
    add_candles(db)
    player = make_player(db)
    assert answer_puzzle(db, player, "long", NOW) == XP_PER_PUZZLE
    assert player.xp == XP_PER_PUZZLE
    assert answer_puzzle(db, player, "short", NOW) == 0
    assert db.query(PuzzleAnswer).filter_by(player_id=player.id).one().choice == "long"
    assert db.query(Event).filter_by(kind="puzzle_done").count() == 1

    result = puzzle_view(db, player, NOW)["result"]
    assert result["correct"] is True
    assert result["answer"] == "long"
    assert result["symbol"] in SYMBOLS
    assert result["trend"] == "up"
    assert result["lesson_id"] in ("06", "07")
    assert len(result["after"]) == PUZZLE_HORIZON
    assert result["after"][0]["time"] == FAKE_EPOCH_S + CANDLE_TIMEFRAME_MS // 1000


def test_wrong_answer_no_xp(db):
    add_candles(db)
    player = make_player(db)
    assert answer_puzzle(db, player, "skip", NOW) == 0
    assert (player.xp or 0) == 0
    result = puzzle_view(db, player, NOW)["result"]
    assert (result["choice"], result["correct"], result["answer"]) == ("skip", False, "long")


def test_bad_choice_rejected(db):
    add_candles(db)
    with pytest.raises(ValueError):
        answer_puzzle(db, make_player(db), "moon", NOW)
