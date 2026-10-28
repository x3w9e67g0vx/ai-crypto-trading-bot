"""Periodic game work run by the scheduler; each takes one DB session and the shared quotes."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.game.config import SeasonKind
from app.game.leaderboard import take_snapshots
from app.game.models import Season
from app.game.quotes import QuoteBook
from app.game.seasons import ensure_current_season, finalize_season
from app.game.trading import check_stops


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
