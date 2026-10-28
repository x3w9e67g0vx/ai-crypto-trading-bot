from app.core.db.models import Candle
from app.game.config import STARTER_SYMBOLS
from tests.api.conftest import auth
from tests.game.conftest import NOW

FIVE_MIN_MS = 5 * 60 * 1000


def test_quotes_lists_unlocked_symbols(client):
    body = client.get("/game/quotes", headers=auth()).json()

    assert body["source"] == "binance"
    assert body["exchange_down"] is False
    assert body["symbols"] == list(STARTER_SYMBOLS)
    btc = next(quote for quote in body["quotes"] if quote["symbol"] == "BTC/USDT")
    assert btc == {"symbol": "BTC/USDT", "bid": 99.0, "ask": 101.0, "ts": NOW, "fresh": True}


def test_quotes_flag_exchange_down(client, clock):
    clock["now"] = NOW + 30_001

    body = client.get("/game/quotes", headers=auth()).json()

    assert body["exchange_down"] is True
    assert all(quote["fresh"] is False for quote in body["quotes"])


def test_candles_ascending_in_seconds(client, db):
    for i in (2, 0, 1):
        ts = NOW + i * FIVE_MIN_MS
        db.add(Candle(symbol="BTC/USDT", timeframe="5m", timestamp=ts, open=1 + i, high=2 + i, low=0.5, close=1.5 + i, volume=10))
    db.add(Candle(symbol="BTC/USDT", timeframe="1h", timestamp=NOW, open=9, high=9, low=9, close=9, volume=9))
    db.add(Candle(symbol="ETH/USDT", timeframe="5m", timestamp=NOW, open=9, high=9, low=9, close=9, volume=9))
    db.commit()

    body = client.get("/game/candles", params={"symbol": "BTC/USDT", "limit": 2}, headers=auth()).json()

    assert body == [
        {"time": (NOW + FIVE_MIN_MS) // 1000, "open": 2, "high": 3, "low": 0.5, "close": 2.5},
        {"time": (NOW + 2 * FIVE_MIN_MS) // 1000, "open": 3, "high": 4, "low": 0.5, "close": 3.5},
    ]


def test_candles_unknown_symbol(client):
    response = client.get("/game/candles", params={"symbol": "FAKE/USDT"}, headers=auth())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "unknown_symbol"
    assert client.get("/game/candles", params={"symbol": "BTC/USDT", "limit": 5000}, headers=auth()).status_code == 422
