"""Closed 5m candles in Postgres: Binance from the stream and REST backfill,
Bybit only while Binance is down (for charts), replaced by Binance later."""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.db.models import Candle, Indicator
from app.game.config import BACKFILL_BATCH, BACKFILL_MAX_BATCHES, CANDLE_TIMEFRAME, CANDLE_TIMEFRAME_MS
from app.game.price_feed import ClosedCandle, valid_candle

logger = logging.getLogger(__name__)

# fetch(symbol, timeframe, since, limit) -> ccxt rows [ts, open, high, low, close, volume]
Fetch = Callable[[str, str, int, int], list[list]]


def store_candle(db: Session, candle: ClosedCandle, *, source: str) -> bool:
    """Binance inserts or overwrites; Bybit only fills a missing candle. True if written."""
    row = (
        db.query(Candle)
        .filter_by(symbol=candle.symbol, timeframe=CANDLE_TIMEFRAME, timestamp=candle.open_time)
        .one_or_none()
    )
    if row is None:
        row = Candle(symbol=candle.symbol, timeframe=CANDLE_TIMEFRAME, timestamp=candle.open_time)
        db.add(row)
    elif source != "binance":
        return False
    elif row.source != "binance":
        # Indicators were computed from the Bybit prices.
        db.query(Indicator).filter_by(candle_id=row.id).delete()
    row.open, row.high, row.low, row.close, row.volume = (
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
    )
    row.source = source
    db.flush()
    return True


def latest_candle(db: Session, symbol: str, *, source: str | None = None) -> Candle | None:
    query = db.query(Candle).filter_by(symbol=symbol, timeframe=CANDLE_TIMEFRAME)
    if source is not None:
        query = query.filter_by(source=source)
    return query.order_by(Candle.timestamp.desc()).first()


def _parse_row(symbol: str, raw: list) -> ClosedCandle | None:
    try:
        candle = ClosedCandle(symbol, int(raw[0]), *(float(value) for value in raw[1:6]))
    except (IndexError, TypeError, ValueError):
        return None
    if not valid_candle(candle.open, candle.high, candle.low, candle.close, candle.volume):
        return None
    return candle


def backfill_candles(db: Session, fetch: Fetch, symbol: str, now_ms: int, *, history_ms: int) -> int:
    """Fetch closed Binance candles after the last stored one (or history_ms back); returns how many were written."""
    last = latest_candle(db, symbol, source="binance")
    if last is not None:
        since = last.timestamp + CANDLE_TIMEFRAME_MS
    else:
        start = now_ms - history_ms
        since = start - start % CANDLE_TIMEFRAME_MS

    written = 0
    for _ in range(BACKFILL_MAX_BATCHES):
        if since + CANDLE_TIMEFRAME_MS > now_ms:
            break
        rows = fetch(symbol, CANDLE_TIMEFRAME, since, BACKFILL_BATCH)
        for raw in rows:
            candle = _parse_row(symbol, raw)
            # ccxt ends with the candle still forming.
            if candle is None or candle.open_time + CANDLE_TIMEFRAME_MS > now_ms:
                continue
            written += store_candle(db, candle, source="binance")
        if len(rows) < BACKFILL_BATCH:
            break
        since = int(rows[-1][0]) + CANDLE_TIMEFRAME_MS
    return written
