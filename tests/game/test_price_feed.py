from app.game.price_feed import ClosedCandle, next_backoff, parse_message, stream_url
from app.game.quotes import Quote


def test_stream_url():
    assert stream_url(["BTC/USDT", "ETH/USDT"]) == (
        "wss://stream.binance.com:9443/stream?streams="
        "btcusdt@bookTicker/btcusdt@kline_1m/ethusdt@bookTicker/ethusdt@kline_1m"
    )


def test_parse_book_ticker():
    raw = {"stream": "btcusdt@bookTicker", "data": {"u": 1, "s": "BTCUSDT", "b": "99.5", "B": "1", "a": "100.5", "A": "2"}}
    assert parse_message(raw, 123) == Quote("BTC/USDT", bid=99.5, ask=100.5, ts=123)


def test_parse_closed_kline_only():
    kline = {"t": 60_000, "s": "ETHUSDT", "i": "1m", "o": "1", "h": "3", "l": "0.5", "c": "2", "v": "10", "x": False}
    raw = {"stream": "ethusdt@kline_1m", "data": {"e": "kline", "s": "ETHUSDT", "k": kline}}
    assert parse_message(raw, 0) is None
    kline["x"] = True
    assert parse_message(raw, 0) == ClosedCandle("ETH/USDT", 60_000, 1.0, 3.0, 0.5, 2.0, 10.0)


def test_parse_unknown_returns_none():
    assert parse_message({"result": None, "id": 1}, 0) is None
    assert parse_message({"stream": "foousdt@bookTicker", "data": {"s": "FOOUSDT", "b": "1", "a": "2"}}, 0) is None


def test_backoff_doubles_up_to_30s():
    assert next_backoff(1) == 2
    assert next_backoff(16) == 30
    assert next_backoff(30) == 30


def book(b, a):
    return {"stream": "btcusdt@bookTicker", "data": {"s": "BTCUSDT", "b": b, "a": a}}


def test_parse_rejects_bad_quotes():
    for b, a in (("nan", "1"), ("1", "inf"), ("0", "1"), ("-1", "1"), ("2", "1"), ("x", "1"), (None, "1")):
        assert parse_message(book(b, a), 0) is None
    assert parse_message({"stream": "btcusdt@bookTicker", "data": {"s": "BTCUSDT"}}, 0) is None


def test_parse_rejects_bad_candles():
    def kline(**over):
        k = {"t": 0, "o": "1", "h": "3", "l": "0.5", "c": "2", "v": "10", "x": True}
        k.update(over)
        return {"stream": "btcusdt@kline_1m", "data": {"e": "kline", "s": "BTCUSDT", "k": k}}

    assert parse_message(kline(), 0) is not None
    for over in ({"h": "1.5"}, {"l": "1.5"}, {"v": "-1"}, {"c": "nan"}, {"l": "0"}, {"t": "x"}, {"x": "true"}):
        assert parse_message(kline(**over), 0) is None
    assert parse_message({"stream": "btcusdt@kline_1m", "data": {"s": "BTCUSDT"}}, 0) is None
