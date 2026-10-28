"""Quotes shared between processes: the price worker writes its QuoteBook to
Postgres, the API, bot and scheduler copy it back into their own books."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.game.models import StoredQuote
from app.game.quotes import Quote, QuoteBook

logger = logging.getLogger(__name__)


def save_quotes(db: Session, quotes: QuoteBook) -> int:
    rows = {row.symbol: row for row in db.query(StoredQuote).all()}
    saved = 0
    for quote in quotes.all():
        row = rows.get(quote.symbol)
        if row is None:
            db.add(StoredQuote(symbol=quote.symbol, bid=quote.bid, ask=quote.ask, ts=quote.ts))
        elif row.ts < quote.ts:
            row.bid, row.ask, row.ts = quote.bid, quote.ask, quote.ts
        else:
            continue
        saved += 1
    db.flush()
    return saved


def load_quotes(db: Session, quotes: QuoteBook) -> int:
    rows = db.query(StoredQuote).all()
    for row in rows:
        quotes.update(Quote(symbol=row.symbol, bid=row.bid, ask=row.ask, ts=row.ts))
    return len(rows)


async def run_quote_sync(session_factory, quotes: QuoteBook, *, publish: bool, interval_s: float = 1.0) -> None:
    """Forever: publish the book (price worker) or refresh it from the table (everyone else)."""
    sync = save_quotes if publish else load_quotes

    def once() -> None:
        with session_factory() as db:
            sync(db, quotes)
            db.commit()

    while True:
        try:
            await asyncio.to_thread(once)
        except Exception:
            logger.exception("quote sync failed")
        await asyncio.sleep(interval_s)
