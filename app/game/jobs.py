"""Periodic game work run by the scheduler; each takes one DB session and the shared quotes."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.game.ai_personas import Signal
from app.game.ai_signals import load_signals
from app.game.ai_trader import run_ai_turn
from app.game.candles import latest_candle
from app.game.config import AI_MAX_LAG_MS, AI_SYMBOLS, CANDLE_TIMEFRAME, CANDLE_TIMEFRAME_MS, SeasonKind
from app.game.leaderboard import take_snapshots
from app.game.models import AiDecision, Season
from app.game.quotes import QuoteBook
from app.game.seasons import ensure_current_season, finalize_season
from app.game.trading import check_stops
from app.services.indicator_service import IndicatorService


def run_seasons(db: Session, quotes: QuoteBook, now_ms: int) -> int:
    """Close every ended season (again, while positions wait for a price), then open the current ones.

    Returns how many seasons were closed by this pass."""
    due = (
        db.query(Season)
        .filter(Season.status.in_(("active", "closing", "voiding")), Season.ends_at <= now_ms)
        .order_by(Season.id)
        .all()
    )
    closed = sum(finalize_season(db, season, quotes, now_ms) for season in due)
    for kind in SeasonKind:
        ensure_current_season(db, kind, now_ms)
    return closed


def run_stops(db: Session, quotes: QuoteBook, now_ms: int) -> int:
    return len(check_stops(db, quotes, now_ms))


def run_snapshots(db: Session, quotes: QuoteBook, now_ms: int) -> int:
    return take_snapshots(db, quotes, now_ms)


class AiJob:
    """AI turns on each pair's latest closed Binance 5m candle, at most once per candle."""

    def __init__(self, signals_loader: Callable[..., dict[str, Signal]] = load_signals) -> None:
        self.signals_loader = signals_loader
        # Last candle tried per pair; kept even without signals so missing models are not re-run every tick.
        self.tried: dict[str, int] = {}

    def run(self, db: Session, quotes: QuoteBook, now_ms: int) -> int:
        """Returns how many pairs the AI traded."""
        traded = 0
        for symbol in AI_SYMBOLS:
            candle = latest_candle(db, symbol)
            if (
                candle is None
                or candle.source != "binance"
                or self.tried.get(symbol) == candle.timestamp
                or candle.timestamp + CANDLE_TIMEFRAME_MS + AI_MAX_LAG_MS < now_ms
            ):
                continue
            self.tried[symbol] = candle.timestamp
            if db.query(AiDecision.id).filter_by(symbol=symbol, candle_ts=candle.timestamp).first():
                continue
            IndicatorService(db).calculate_and_save(symbol, CANDLE_TIMEFRAME)
            signals = self.signals_loader(db, symbol, candle.timestamp)
            if signals and run_ai_turn(db, symbol, candle.timestamp, signals, quotes, now_ms):
                traded += 1
        return traded
