from __future__ import annotations

from dataclasses import dataclass

from app.game.config import STALE_AFTER_MS
from app.game.errors import StaleQuote


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    ts: int


class QuoteBook:
    """Latest best bid/ask per symbol, fed by the Binance stream."""

    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}

    def update(self, quote: Quote) -> None:
        current = self._quotes.get(quote.symbol)
        if current is not None and current.ts > quote.ts:
            return
        self._quotes[quote.symbol] = quote

    def last(self, symbol: str) -> Quote | None:
        return self._quotes.get(symbol)

    def get(self, symbol: str, now_ms: int) -> Quote:
        quote = self._quotes.get(symbol)
        if quote is None or now_ms - quote.ts > STALE_AFTER_MS:
            raise StaleQuote(symbol)
        return quote

    def is_fresh(self, symbol: str, now_ms: int) -> bool:
        quote = self._quotes.get(symbol)
        return quote is not None and now_ms - quote.ts <= STALE_AFTER_MS

    def last_update_ms(self) -> int | None:
        if not self._quotes:
            return None
        return max(quote.ts for quote in self._quotes.values())
