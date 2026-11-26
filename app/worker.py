"""Price worker: `python -m app.worker`.

Keeps Binance bid/ask in the `quotes` table for the other processes, stores
closed 5m candles, backfills gaps over REST after a restart or reconnect, and
fills chart candles from Bybit while Binance is down.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from sqlalchemy.exc import IntegrityError

from app.game.bybit_feed import BybitFeed
from app.game.candles import Fetch, backfill_candles, store_candle
from app.game.config import DAY_MS, GAME_SYMBOLS, STALE_AFTER_MS
from app.game.price_feed import BinanceFeed, ClosedCandle
from app.game.quote_store import run_quote_sync
from app.game.quotes import QuoteBook

logger = logging.getLogger(__name__)

# How far back to fetch candles for a pair with none stored yet.
CANDLE_HISTORY_DAYS = int(os.getenv("CANDLE_HISTORY_DAYS", "30"))
# Exit (Docker restarts us) when Binance has been silent this long: on 2026-11-26
# the container lost DNS and the feeds never recovered on their own.
# shortcut: a real Binance outage also restarts us every 5 min (Bybit candles pause briefly), fine until outages get long.
WORKER_STALE_EXIT_MS = 5 * 60 * 1000


def _now_ms() -> int:
    return int(time.time() * 1000)


def binance_healthy(quotes: QuoteBook, now_ms: int) -> bool:
    last = quotes.last_update_ms()
    return last is not None and now_ms - last <= STALE_AFTER_MS


async def watch_quotes(quotes: QuoteBook, now=_now_ms, max_age_ms: int = WORKER_STALE_EXIT_MS, check_every_s: float = 30) -> None:
    """Returns once no Binance quote is newer than max_age_ms (counted from start if none came)."""
    started = now()
    while True:
        await asyncio.sleep(check_every_s)
        last = max(quotes.last_update_ms() or started, started)
        if now() - last > max_age_ms:
            return


def _store(session_factory, candle: ClosedCandle, source: str) -> bool:
    with session_factory() as db:
        try:
            written = store_candle(db, candle, source=source)
            db.commit()
        except IntegrityError:
            # The same candle was just written by the backfill or the other feed.
            db.rollback()
            return False
    return written


def handle_binance_candle(session_factory, candle: ClosedCandle) -> None:
    _store(session_factory, candle, "binance")


def handle_bybit_candle(session_factory, quotes: QuoteBook, candle: ClosedCandle, now_ms: int) -> bool:
    """Bybit fills chart candles only while Binance is silent."""
    if binance_healthy(quotes, now_ms):
        return False
    return _store(session_factory, candle, "bybit")


def backfill_all(session_factory, fetch: Fetch, now_ms: int, history_ms: int) -> int:
    written = 0
    for symbol in GAME_SYMBOLS:
        with session_factory() as db:
            try:
                written += backfill_candles(db, fetch, symbol, now_ms, history_ms=history_ms)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("backfill of %s failed", symbol)
    return written


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from app.core.db.session import SessionLocal
    from app.services.exchange_service import ExchangeService

    exchange = ExchangeService()

    def fetch(symbol: str, timeframe: str, since: int, limit: int) -> list[list]:
        return exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit, since=since)

    history_ms = CANDLE_HISTORY_DAYS * DAY_MS
    quotes = QuoteBook()

    async def backfill(_last_candle_ms: int | None = None) -> None:
        written = await asyncio.to_thread(backfill_all, SessionLocal, fetch, _now_ms(), history_ms)
        logger.info("backfilled %d candles", written)

    async def on_binance(candle: ClosedCandle) -> None:
        await asyncio.to_thread(handle_binance_candle, SessionLocal, candle)

    async def on_bybit(candle: ClosedCandle) -> None:
        await asyncio.to_thread(handle_bybit_candle, SessionLocal, quotes, candle, _now_ms())

    binance = BinanceFeed(quotes, on_candle=on_binance, on_reconnect=backfill)
    bybit = BybitFeed(on_bybit)
    tasks = [
        asyncio.create_task(binance.run()),
        asyncio.create_task(bybit.run()),
        asyncio.create_task(run_quote_sync(SessionLocal, quotes, publish=True)),
        asyncio.create_task(backfill()),
    ]

    async def exit_when_stale() -> None:
        await watch_quotes(quotes)
        raise RuntimeError(f"no Binance quotes for {WORKER_STALE_EXIT_MS // 1000} s, exiting so Docker restarts the worker")

    tasks.append(asyncio.create_task(exit_when_stale()))
    try:
        await asyncio.gather(*tasks)
    finally:
        binance.stop()
        bybit.stop()
        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
