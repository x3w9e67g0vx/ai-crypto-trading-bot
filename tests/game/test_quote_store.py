import pytest

from app.game.errors import StaleQuote
from app.game.models import StoredQuote
from app.game.quote_store import load_quotes, save_quotes
from app.game.quotes import Quote, QuoteBook
from tests.game.conftest import NOW


def test_save_then_load_roundtrip(db, quotes):
    assert save_quotes(db, quotes) == 2
    db.commit()

    book = QuoteBook()
    assert load_quotes(db, book) == 2
    assert book.get("BTC/USDT", NOW) == Quote("BTC/USDT", bid=99.0, ask=101.0, ts=NOW)
    assert book.get("ETH/USDT", NOW) == Quote("ETH/USDT", bid=99.0, ask=101.0, ts=NOW)


def test_save_updates_and_keeps_newer_row(db):
    db.add(StoredQuote(symbol="BTC/USDT", bid=1.0, ask=2.0, ts=200))
    db.flush()

    old = QuoteBook()
    old.update(Quote("BTC/USDT", bid=5.0, ask=6.0, ts=100))
    save_quotes(db, old)
    assert db.get(StoredQuote, "BTC/USDT").ts == 200

    new = QuoteBook()
    new.update(Quote("BTC/USDT", bid=7.0, ask=8.0, ts=300))
    save_quotes(db, new)
    row = db.get(StoredQuote, "BTC/USDT")
    assert (row.bid, row.ask, row.ts) == (7.0, 8.0, 300)


def test_loaded_quotes_go_stale(db, quotes):
    # The worker stopped publishing: the copied quote keeps its receipt time and ages out.
    save_quotes(db, quotes)
    book = QuoteBook()
    load_quotes(db, book)
    load_quotes(db, book)
    with pytest.raises(StaleQuote):
        book.get("BTC/USDT", NOW + 31_000)
