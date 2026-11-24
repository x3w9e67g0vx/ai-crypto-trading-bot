import pytest

from app.core.db.models import Candle
from app.game.config import CANDLE_TIMEFRAME_MS, GUESS_DAILY_XP_CAP, GUESS_GRACE_MS, XP_PER_GUESS_HIT
from app.game.errors import AlreadyGuessed, UnknownSymbol
from app.game.guesses import guess_view, majority_view, make_guess, settle_guesses, target_candle
from app.game.models import AiDecision
from tests.game.conftest import NOW, make_player

STEP = CANDLE_TIMEFRAME_MS
NEXT = NOW + STEP  # NOW sits on a candle boundary
CLOSED = NEXT + STEP


def add_candle(db, ts, open_, close, symbol="BTC/USDT"):
    db.add(Candle(symbol=symbol, timeframe="5m", timestamp=ts, open=open_, high=max(open_, close),
                  low=min(open_, close), close=close, volume=1.0))
    db.flush()


def add_ai_views(db, ts, *views, symbol="BTC/USDT"):
    for i, view in enumerate(views):
        ai = make_player(db, nickname=f"ai{ts}{i}", is_ai=True, ai_key=f"k{ts}{i}")
        db.add(AiDecision(player_id=ai.id, symbol=symbol, candle_ts=ts, probability_up=0.5, view=view, created_at=ts))
    db.flush()


@pytest.fixture
def player(db):
    return make_player(db, telegram_id=1)


def test_target_is_the_next_candle():
    assert target_candle(NOW) == NEXT
    assert target_candle(NOW + STEP - 1) == NEXT


@pytest.mark.parametrize(
    ("views", "expected"),
    [([], None), (["bullish"], "bullish"), (["bullish", "bearish"], "neutral"),
     (["bearish", "bearish", "bullish"], "bearish")],
)
def test_majority_view(views, expected):
    assert majority_view(views) == expected


def test_one_guess_per_candle_and_known_symbols(db, player):
    make_guess(db, player, "BTC/USDT", "up", "bullish", NOW)
    with pytest.raises(AlreadyGuessed):
        make_guess(db, player, "BTC/USDT", "down", "bearish", NOW + 1000)
    make_guess(db, player, "ETH/USDT", "up", "bullish", NOW)
    with pytest.raises(UnknownSymbol):
        make_guess(db, player, "DOGE/USDT", "up", "bullish", NOW)
    with pytest.raises(ValueError):
        make_guess(db, player, "SOL/USDT", "sideways", "bullish", NOW)


def test_settles_after_close_with_xp_per_hit(db, player):
    make_guess(db, player, "BTC/USDT", "up", "bearish", NOW)
    add_candle(db, NEXT, 100.0, 101.0)
    add_ai_views(db, NEXT, "bullish", "bullish", "neutral")
    assert settle_guesses(db, player, NEXT + STEP - 1) == 0  # candle still open
    assert settle_guesses(db, player, CLOSED) == XP_PER_GUESS_HIT
    view = guess_view(db, player, "BTC/USDT", CLOSED)
    assert (view["recent"][0]["price_correct"], view["recent"][0]["ai_correct"]) == (True, False)
    assert player.xp == XP_PER_GUESS_HIT
    assert settle_guesses(db, player, CLOSED + STEP) == 0  # settled once


def test_waits_for_ai_then_settles_price_only(db, player):
    make_guess(db, player, "BTC/USDT", "down", "bullish", NOW)
    add_candle(db, NEXT, 100.0, 99.0)
    assert settle_guesses(db, player, CLOSED) == 0
    assert guess_view(db, player, "BTC/USDT", CLOSED)["pending"] == 1
    assert settle_guesses(db, player, CLOSED + GUESS_GRACE_MS) == XP_PER_GUESS_HIT
    view = guess_view(db, player, "BTC/USDT", CLOSED + GUESS_GRACE_MS)
    assert view["recent"][0]["ai_correct"] is None and view["pending"] == 0


def test_flat_candle_is_a_miss(db, player):
    make_guess(db, player, "BTC/USDT", "up", "neutral", NOW)
    add_candle(db, NEXT, 100.0, 100.0)
    add_ai_views(db, NEXT, "neutral")
    assert settle_guesses(db, player, CLOSED) == XP_PER_GUESS_HIT


def test_daily_xp_cap(db, player):
    hits = GUESS_DAILY_XP_CAP // (2 * XP_PER_GUESS_HIT) + 2
    for i in range(hits):
        ts = NOW + i * STEP
        make_guess(db, player, "BTC/USDT", "up", "bullish", ts)
        add_candle(db, ts + STEP, 100.0, 101.0)
        add_ai_views(db, ts + STEP, "bullish")
    assert settle_guesses(db, player, NOW + (hits + 2) * STEP) == GUESS_DAILY_XP_CAP
    assert player.xp == GUESS_DAILY_XP_CAP


def test_view_shows_current_guess(db, player):
    assert guess_view(db, player, "BTC/USDT", NOW)["current"] is None
    make_guess(db, player, "BTC/USDT", "up", "bullish", NOW)
    view = guess_view(db, player, "BTC/USDT", NOW + 1000)
    assert view["candle_ts"] == NEXT
    assert (view["current"]["price"], view["current"]["view"]) == ("up", "bullish")
    assert guess_view(db, player, "ETH/USDT", NOW)["current"] is None
