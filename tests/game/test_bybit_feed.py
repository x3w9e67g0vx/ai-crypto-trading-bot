from app.game.bybit_feed import parse_bybit_message, subscribe_messages
from app.game.config import GAME_SYMBOLS
from app.game.price_feed import ClosedCandle


def kline(confirm=True, **over):
    item = {
        "start": 300_000,
        "end": 599_999,
        "interval": "5",
        "open": "1",
        "close": "2",
        "high": "3",
        "low": "0.5",
        "volume": "10",
        "confirm": confirm,
        "timestamp": 600_000,
    }
    item.update(over)
    return item


def message(*items, topic="kline.5.BTCUSDT"):
    return {"topic": topic, "type": "snapshot", "ts": 600_001, "data": list(items)}


def test_subscribe_in_chunks_of_ten():
    messages = subscribe_messages(GAME_SYMBOLS)
    assert [len(m["args"]) for m in messages] == [10, 10]
    assert all(m["op"] == "subscribe" for m in messages)
    assert messages[0]["args"][0] == "kline.5.BTCUSDT"
    assert sum((m["args"] for m in messages), []) == [f"kline.5.{s.replace('/', '')}" for s in GAME_SYMBOLS]


def test_parse_confirmed_kline():
    assert parse_bybit_message(message(kline())) == [ClosedCandle("BTC/USDT", 300_000, 1.0, 3.0, 0.5, 2.0, 10.0)]


def test_parse_skips_unconfirmed_and_unknown():
    assert parse_bybit_message(message(kline(confirm=False))) == []
    assert parse_bybit_message(message(kline(), topic="kline.5.FOOUSDT")) == []
    assert parse_bybit_message(message(kline(), topic="kline.1.BTCUSDT")) == []


def test_parse_rejects_bad_values():
    for over in ({"high": "1.5"}, {"low": "0"}, {"volume": "-1"}, {"close": "nan"}, {"start": "x"}, {"open": None}):
        assert parse_bybit_message(message(kline(**over))) == [], over
    assert parse_bybit_message({"topic": "kline.5.BTCUSDT", "data": "oops"}) == []


def test_parse_ignores_pong_and_acks():
    assert parse_bybit_message({"success": True, "ret_msg": "pong", "op": "ping"}) == []
    assert parse_bybit_message({"success": True, "ret_msg": "", "op": "subscribe"}) == []
