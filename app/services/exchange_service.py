from __future__ import annotations

from typing import Any

import ccxt

from app.core.config import settings


class ExchangeService:
    def __init__(self) -> None:
        exchange_class = getattr(ccxt, settings.EXCHANGE_NAME)
        self.exchange = exchange_class(
            {
                "enableRateLimit": True,
            }
        )

    def load_markets(self) -> dict[str, Any]:
        return self.exchange.load_markets()

    def fetch_ohlcv(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int | None = None,
    ) -> list[list[float]]:
        return self.exchange.fetch_ohlcv(
            symbol=symbol or settings.DEFAULT_SYMBOL,
            timeframe=timeframe or settings.DEFAULT_TIMEFRAME,
            limit=limit or settings.OHLCV_LIMIT,
        )
