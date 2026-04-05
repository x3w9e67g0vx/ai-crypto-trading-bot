from __future__ import annotations

from typing import Any

from app.services.exchange_service import ExchangeService


class MarketDataService:
    def __init__(self) -> None:
        self.exchange_service = ExchangeService()

    def get_markets(self) -> list[str]:
        markets = self.exchange_service.load_markets()
        return sorted(markets.keys())

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        since: int | None = None,
    ) -> list[dict[str, Any]]:
        raw_ohlcv = self.exchange_service.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            since=since,
        )

        return [
            {
                "timestamp": candle[0],
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
                "volume": candle[5],
            }
            for candle in raw_ohlcv
        ]

    def get_available_symbols(
        self,
        quote: str | None = "USDT",
        only_active: bool = True,
        limit: int = 100,
        spot_only: bool = True,
    ) -> list[str]:
        markets = self.exchange_service.load_markets()

        symbols = []

        for symbol, market in markets.items():
            if quote and market.get("quote") != quote:
                continue

            if only_active and not market.get("active", True):
                continue

            if spot_only:
                if ":" in symbol:
                    continue
                if not market.get("spot", False):
                    continue

            symbols.append(symbol)

        symbols = sorted(symbols)
        return symbols[:limit]
