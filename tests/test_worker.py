from app.core.db.models import Candle
from app.game.price_feed import ClosedCandle
from app.game.quotes import QuoteBook
from app.worker import backfill_all, binance_healthy, handle_binance_candle, handle_bybit_candle
from tests.api.conftest import quotes, session_factory  # noqa: F401  shared fixtures
from tests.game.conftest import NOW

CANDLE = ClosedCandle("BTC/USDT", NOW - 300_000, 1.0, 3.0, 0.5, 2.0, 10.0)


def stored(session_factory):
    with session_factory() as db:
        return [(c.symbol, c.timestamp, c.source) for c in db.query(Candle).order_by(Candle.symbol).all()]


def test_binance_healthy(quotes):
    assert binance_healthy(quotes, NOW + 30_000)
    assert not binance_healthy(quotes, NOW + 30_001)
    assert not binance_healthy(QuoteBook(), NOW)


def test_bybit_candle_ignored_while_binance_healthy(session_factory, quotes):
    assert handle_bybit_candle(session_factory, quotes, CANDLE, NOW + 1_000) is False
    assert stored(session_factory) == []


def test_bybit_candle_stored_when_binance_stale(session_factory, quotes):
    assert handle_bybit_candle(session_factory, quotes, CANDLE, NOW + 60_000) is True
    assert stored(session_factory) == [("BTC/USDT", CANDLE.open_time, "bybit")]


def test_bybit_candle_stored_when_no_quotes(session_factory):
    assert handle_bybit_candle(session_factory, QuoteBook(), CANDLE, NOW) is True


def test_binance_candle_stored(session_factory):
    handle_binance_candle(session_factory, CANDLE)
    assert stored(session_factory) == [("BTC/USDT", CANDLE.open_time, "binance")]


def test_backfill_all_survives_one_symbol_error(session_factory, monkeypatch):
    monkeypatch.setattr("app.worker.GAME_SYMBOLS", ("BTC/USDT", "ETH/USDT"))

    def fetch(symbol, timeframe, since, limit):
        if symbol == "BTC/USDT":
            raise RuntimeError("exchange down")
        return [[NOW - 300_000, 1.0, 3.0, 0.5, 2.0, 10.0]]

    assert backfill_all(session_factory, fetch, NOW, history_ms=600_000) == 1
    assert stored(session_factory) == [("ETH/USDT", NOW - 300_000, "binance")]
