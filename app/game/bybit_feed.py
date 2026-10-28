"""Bybit spot 5m klines: a chart fallback while Binance is down, never used for fills."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable

import aiohttp

from app.game.config import GAME_SYMBOLS
from app.game.price_feed import ClosedCandle, next_backoff, valid_candle

logger = logging.getLogger(__name__)

BYBIT_SPOT_URL = "wss://stream.bybit.com/v5/public/spot"
# Bybit takes at most 10 topics per spot subscribe request.
SUBSCRIBE_CHUNK = 10
PING_INTERVAL_S = 20
TOPIC_PREFIX = "kline.5."

_SYMBOLS_BY_NAME = {symbol.replace("/", ""): symbol for symbol in GAME_SYMBOLS}


def subscribe_messages(symbols: Iterable[str]) -> list[dict]:
    topics = [TOPIC_PREFIX + symbol.replace("/", "") for symbol in symbols]
    return [
        {"op": "subscribe", "args": topics[i : i + SUBSCRIBE_CHUNK]}
        for i in range(0, len(topics), SUBSCRIBE_CHUNK)
    ]


def parse_bybit_message(raw: dict) -> list[ClosedCandle]:
    """Confirmed (closed) candles in one message; acks, pongs and bad data give nothing."""
    topic = raw.get("topic")
    data = raw.get("data")
    if not isinstance(topic, str) or not topic.startswith(TOPIC_PREFIX) or not isinstance(data, list):
        return []
    symbol = _SYMBOLS_BY_NAME.get(topic.removeprefix(TOPIC_PREFIX))
    if symbol is None:
        return []

    candles = []
    for item in data:
        try:
            if item.get("confirm") is not True:
                continue
            candle = ClosedCandle(
                symbol=symbol,
                open_time=int(item["start"]),
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(item["volume"]),
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if valid_candle(candle.open, candle.high, candle.low, candle.close, candle.volume):
            candles.append(candle)
    return candles


class BybitFeed:
    """Passes closed Bybit 5m candles to on_candle, reconnecting forever."""

    def __init__(
        self,
        on_candle: Callable[[ClosedCandle], Awaitable[None]],
        symbols: Iterable[str] = GAME_SYMBOLS,
    ) -> None:
        self.on_candle = on_candle
        self.symbols = list(symbols)
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        backoff = 1.0
        async with aiohttp.ClientSession() as session:
            while not self._stopped:
                try:
                    async with session.ws_connect(BYBIT_SPOT_URL) as ws:
                        backoff = 1.0
                        for request in subscribe_messages(self.symbols):
                            await ws.send_json(request)
                        pinger = asyncio.create_task(self._ping(ws))
                        try:
                            await self._consume(ws)
                        finally:
                            pinger.cancel()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("bybit stream error, reconnecting")
                if self._stopped:
                    break
                await asyncio.sleep(backoff)
                backoff = next_backoff(backoff)

    async def _ping(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL_S)
            await ws.send_json({"op": "ping"})

    async def _consume(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for message in ws:
            if self._stopped:
                return
            if message.type != aiohttp.WSMsgType.TEXT:
                if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    return
                continue
            try:
                raw = json.loads(message.data)
            except ValueError:
                continue
            if not isinstance(raw, dict):
                continue
            for candle in parse_bybit_message(raw):
                await self.on_candle(candle)
