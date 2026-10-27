import pytest

from app.game.errors import StaleQuote
from app.game.quotes import Quote, QuoteBook


def test_get_fresh_quote():
    book = QuoteBook()
    book.update(Quote("BTC/USDT", bid=1.0, ask=2.0, ts=1000))
    assert book.get("BTC/USDT", 2000).ask == 2.0
    assert book.last_update_ms() == 1000


def test_stale_after_30_seconds():
    book = QuoteBook()
    book.update(Quote("BTC/USDT", bid=1.0, ask=2.0, ts=0))
    assert book.get("BTC/USDT", 30_000).bid == 1.0
    assert book.is_fresh("BTC/USDT", 30_000)
    with pytest.raises(StaleQuote):
        book.get("BTC/USDT", 30_001)
    assert not book.is_fresh("BTC/USDT", 30_001)


def test_missing_symbol_is_stale():
    book = QuoteBook()
    with pytest.raises(StaleQuote):
        book.get("ETH/USDT", 0)
    assert book.last_update_ms() is None


def test_older_update_ignored():
    book = QuoteBook()
    book.update(Quote("BTC/USDT", bid=5.0, ask=6.0, ts=2000))
    book.update(Quote("BTC/USDT", bid=1.0, ask=2.0, ts=1000))
    assert book.get("BTC/USDT", 2000).bid == 5.0
    assert book.last("BTC/USDT").bid == 5.0
