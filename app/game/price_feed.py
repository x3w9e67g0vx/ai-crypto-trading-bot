from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

import aiohttp

from app.game.config import GAME_SYMBOLS
from app.game.quotes import Quote, QuoteBook

logger = logging.getLogger(__name__)

BINANCE_STREAM_BASE = "wss://stream.binance.com:9443/stream?streams="
MAX_BACKOFF_SECONDS = 30

_SYMBOLS_BY_STREAM_NAME = {symbol.replace("/", ""): symbol for symbol in GAME_SYMBOLS}


@dataclass(frozen=True)
class ClosedCandle:
    symbol: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def stream_url(symbols: Iterable[str]) -> str:
    streams = []
    for symbol in symbols:
        name = symbol.replace("/", "").lower()
        streams += [f"{name}@bookTicker", f"{name}@kline_1m"]
    return BINANCE_STREAM_BASE + "/".join(streams)


def parse_message(raw: dict, now_ms: int) -> Quote | ClosedCandle | None:
    """Turn one combined-stream message into a quote or a closed 1m candle."""
    data = raw.get("data")
    if not isinstance(data, dict):
        return None
    symbol = _SYMBOLS_BY_STREAM_NAME.get(data.get("s", ""))
    if symbol is None:
        return None

    if data.get("e") == "kline":
        kline = data["k"]
        if not kline.get("x"):
            return None
        return ClosedCandle(
            symbol=symbol,
            open_time=int(kline["t"]),
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
        )
    if "b" in data and "a" in data:
        # bookTicker carries no event time; stamp it on receipt.
        return Quote(symbol=symbol, bid=float(data["b"]), ask=float(data["a"]), ts=now_ms)
    return None


def next_backoff(current: float) -> float:
    return min(current * 2, MAX_BACKOFF_SECONDS)


def _now_ms() -> int:
    return int(time.time() * 1000)


class BinanceFeed:
    """Keeps a QuoteBook current from Binance spot WebSocket streams, reconnecting forever."""

    def __init__(
        self,
        quotes: QuoteBook,
        symbols: Iterable[str] = GAME_SYMBOLS,
        on_candle: Callable[[ClosedCandle], Awaitable[None]] | None = None,
        on_reconnect: Callable[[int | None], Awaitable[None]] | None = None,
    ) -> None:
        self.quotes = quotes
        self.url = stream_url(symbols)
        self.on_candle = on_candle
        # Called with the last closed candle time so the gap can be backfilled over REST.
        self.on_reconnect = on_reconnect
        self.last_candle_ms: int | None = None
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        backoff = 1.0
        connected_before = False
        async with aiohttp.ClientSession() as session:
            while not self._stopped:
                try:
                    async with session.ws_connect(self.url, heartbeat=20) as ws:
                        backoff = 1.0
                        if connected_before and self.on_reconnect is not None:
                            await self.on_reconnect(self.last_candle_ms)
                        connected_before = True
                        await self._consume(ws)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning("binance stream error: %s", exc)
                if self._stopped:
                    break
                await asyncio.sleep(backoff)
                backoff = next_backoff(backoff)

    async def _consume(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for message in ws:
            if self._stopped:
                return
            if message.type != aiohttp.WSMsgType.TEXT:
                if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    return
                continue
            event = parse_message(json.loads(message.data), _now_ms())
            if isinstance(event, Quote):
                self.quotes.update(event)
            elif isinstance(event, ClosedCandle):
                self.last_candle_ms = event.open_time
                if self.on_candle is not None:
                    await self.on_candle(event)
