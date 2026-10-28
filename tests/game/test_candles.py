from app.core.db.models import Candle, Indicator
from app.game.candles import backfill_candles, latest_candle, store_candle
from app.game.price_feed import ClosedCandle
from tests.game.conftest import NOW

M5 = 300_000
# NOW is 12:00 UTC, so it is a 5m boundary.
LAST_CLOSED = NOW - M5


def candle(ts, close=2.0, symbol="BTC/USDT"):
    return ClosedCandle(symbol, ts, 1.0, 3.0, 0.5, close, 10.0)


def row(ts, close=2.0):
    return [ts, 1.0, 3.0, 0.5, close, 10.0]


class FakeFetch:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __call__(self, symbol, timeframe, since, limit):
        self.calls.append((symbol, timeframe, since, limit))
        return [r for r in self.rows if r[0] >= since][:limit]


def test_store_candle_insert_and_update(db):
    assert store_candle(db, candle(LAST_CLOSED), source="binance") is True
    assert store_candle(db, candle(LAST_CLOSED, close=2.5), source="binance") is True
    rows = db.query(Candle).all()
    assert len(rows) == 1
    assert (rows[0].timeframe, rows[0].close, rows[0].source) == ("5m", 2.5, "binance")


def test_binance_candle_replaces_bybit(db):
    store_candle(db, candle(LAST_CLOSED, close=2.1), source="bybit")
    stored = db.query(Candle).one()
    db.add(Indicator(candle_id=stored.id, rsi=50.0))
    db.flush()

    assert store_candle(db, candle(LAST_CLOSED, close=2.4), source="binance") is True
    stored = db.query(Candle).one()
    assert (stored.close, stored.source) == (2.4, "binance")
    assert db.query(Indicator).count() == 0


def test_bybit_never_overwrites(db):
    store_candle(db, candle(LAST_CLOSED, close=2.4), source="binance")
    assert store_candle(db, candle(LAST_CLOSED, close=2.1), source="bybit") is False
    store_candle(db, candle(LAST_CLOSED - M5, close=2.1), source="bybit")
    assert store_candle(db, candle(LAST_CLOSED - M5, close=2.2), source="bybit") is False
    assert db.query(Candle).filter_by(timestamp=LAST_CLOSED).one().close == 2.4
    assert db.query(Candle).filter_by(timestamp=LAST_CLOSED - M5).one().close == 2.1


def test_latest_candle_by_source(db):
    store_candle(db, candle(LAST_CLOSED - M5), source="binance")
    store_candle(db, candle(LAST_CLOSED), source="bybit")
    assert latest_candle(db, "BTC/USDT").timestamp == LAST_CLOSED
    assert latest_candle(db, "BTC/USDT", source="binance").timestamp == LAST_CLOSED - M5
    assert latest_candle(db, "ETH/USDT") is None


def test_backfill_from_last_binance_candle(db):
    store_candle(db, candle(LAST_CLOSED - 3 * M5), source="binance")
    store_candle(db, candle(LAST_CLOSED - M5), source="bybit")
    fetch = FakeFetch([row(LAST_CLOSED - 2 * M5), row(LAST_CLOSED - M5), row(LAST_CLOSED)])

    assert backfill_candles(db, fetch, "BTC/USDT", NOW, history_ms=10 * M5) == 3
    assert fetch.calls[0] == ("BTC/USDT", "5m", LAST_CLOSED - 2 * M5, 500)
    assert db.query(Candle).filter_by(source="bybit").count() == 0
    assert db.query(Candle).count() == 4


def test_backfill_from_history_when_empty(db):
    fetch = FakeFetch([])
    backfill_candles(db, fetch, "BTC/USDT", NOW + 123, history_ms=10 * M5 + 7)
    assert fetch.calls == [("BTC/USDT", "5m", NOW - 10 * M5, 500)]


def test_backfill_skips_open_candle(db):
    # ccxt returns the candle still forming as the last row.
    fetch = FakeFetch([row(LAST_CLOSED), row(NOW)])
    assert backfill_candles(db, fetch, "BTC/USDT", NOW + 60_000, history_ms=M5) == 1
    assert [c.timestamp for c in db.query(Candle).all()] == [LAST_CLOSED]


def test_backfill_pages_until_short_batch(db, monkeypatch):
    monkeypatch.setattr("app.game.candles.BACKFILL_BATCH", 2)
    fetch = FakeFetch([row(LAST_CLOSED - k * M5) for k in range(4, -1, -1)])
    assert backfill_candles(db, fetch, "BTC/USDT", NOW, history_ms=5 * M5) == 5
    assert [call[2] for call in fetch.calls] == [LAST_CLOSED - 4 * M5, LAST_CLOSED - 2 * M5, LAST_CLOSED]


def test_backfill_skips_invalid_rows(db):
    bad = [LAST_CLOSED - M5, 1.0, 0.9, 0.5, 2.0, 10.0]  # high below close
    fetch = FakeFetch([bad, row(LAST_CLOSED)])
    assert backfill_candles(db, fetch, "BTC/USDT", NOW, history_ms=2 * M5) == 1
    assert db.query(Candle).count() == 1
