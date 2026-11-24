import random

import pytest

from app.core.db.models import Candle
from app.game.config import CANDLE_TIMEFRAME_MS, DAY_MS, REPLAY_CANDLES, REPLAY_SHOW, XP_PER_REPLAY
from app.game.replay import finish_replay, replay_view
from app.game.streaks import active_days, streak_length
from tests.game.conftest import NOW, make_player


def add_candles(db, *, days=10, symbols=("BTC/USDT", "ETH/USDT", "SOL/USDT"), skip=()):
    end = NOW - NOW % CANDLE_TIMEFRAME_MS
    count = days * DAY_MS // CANDLE_TIMEFRAME_MS
    for symbol in symbols:
        for i in range(count):
            if i in skip:
                continue
            price = 100.0 + i
            db.add(Candle(symbol=symbol, timeframe="5m", timestamp=end - (count - i) * CANDLE_TIMEFRAME_MS,
                          open=price, high=price + 2, low=price - 1, close=price + 1, volume=1.0, source="binance"))
    db.flush()


def test_no_history_no_replay(db):
    add_candles(db, days=5)  # a week doesn't fit
    assert replay_view(db, NOW) is None


def test_replay_groups_5m_into_hours(db):
    add_candles(db)
    view = replay_view(db, NOW, random.Random(1))
    candles = view["candles"]
    assert len(candles) == REPLAY_CANDLES
    assert view["show"] == REPLAY_SHOW and view["xp"] == XP_PER_REPLAY
    assert view["symbol"] in ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    first, second = candles[0], candles[1]
    assert second["time"] - first["time"] == 3600
    # 12 rising 5m candles: open of the first, close of the last, extremes over all.
    assert first["close"] - first["open"] == pytest.approx(12)
    assert first["high"] == pytest.approx(first["open"] + 11 + 2)
    assert first["low"] == pytest.approx(first["open"] - 1)


def test_gaps_are_skipped(db):
    count = 10 * DAY_MS // CANDLE_TIMEFRAME_MS
    add_candles(db, skip=set(range(0, count, 500)))
    assert replay_view(db, NOW, random.Random(1)) is None


def test_finish_gives_xp_once_per_day_and_counts_for_streak(db):
    player = make_player(db)
    assert finish_replay(db, player, NOW) == XP_PER_REPLAY
    assert finish_replay(db, player, NOW + 1000) == 0
    assert player.xp == XP_PER_REPLAY
    assert streak_length(active_days(db, player.id, NOW), NOW // DAY_MS) == (1, True)
