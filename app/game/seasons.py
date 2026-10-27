from __future__ import annotations

from sqlalchemy.orm import Session

from app.game.config import DAY_MS, STARTING_BALANCE, WEEK_MS, SeasonKind
from app.game.errors import SeasonClosed
from app.game.models import Player, Portfolio, Position, Season
from app.game.quotes import QuoteBook
from app.game.trading import close_position

# 1970-01-01 was a Thursday; Monday 1970-01-05 00:00 UTC anchors weeks.
_FIRST_MONDAY_MS = 4 * DAY_MS


def season_bounds(kind: SeasonKind, at_ms: int) -> tuple[int, int]:
    if kind == SeasonKind.SPRINT:
        start = at_ms - at_ms % DAY_MS
        return start, start + DAY_MS
    start = at_ms - (at_ms - _FIRST_MONDAY_MS) % WEEK_MS
    return start, start + WEEK_MS


def ensure_current_season(db: Session, kind: SeasonKind, now_ms: int) -> Season:
    starts_at, ends_at = season_bounds(kind, now_ms)
    season = db.query(Season).filter_by(kind=kind.value, starts_at=starts_at).one_or_none()
    if season is None:
        season = Season(kind=kind.value, starts_at=starts_at, ends_at=ends_at, status="active")
        db.add(season)
        db.flush()
    return season


def join_season(db: Session, player: Player, season: Season, now_ms: int) -> Portfolio:
    portfolio = db.query(Portfolio).filter_by(player_id=player.id, season_id=season.id).one_or_none()
    if portfolio is not None:
        return portfolio
    if player.is_banned or season.status != "active":
        raise SeasonClosed(season.id)

    portfolio = Portfolio(
        player_id=player.id,
        season_id=season.id,
        cash=STARTING_BALANCE,
        created_at=now_ms,
    )
    db.add(portfolio)
    db.flush()
    if season.kind == SeasonKind.WEEK.value and not player.is_ai:
        from app.game.leagues import assign_group

        assign_group(db, portfolio, season, now_ms)
    return portfolio


def finalize_season(db: Session, season: Season, quotes: QuoteBook, now_ms: int) -> bool:
    """Close a finished season. Returns False while positions still await a fresh price."""
    if season.status == "finished":
        return True
    if now_ms < season.ends_at:
        return False
    season.status = "closing"

    remaining = (
        db.query(Position)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .filter(Portfolio.season_id == season.id, Position.closed_at.is_(None))
        .order_by(Position.id)
        .all()
    )
    pending = 0
    for position in remaining:
        if not quotes.is_fresh(position.symbol, now_ms):
            pending += 1
            continue
        close_position(db, position, quotes, now_ms, reason="season_end", is_user=False)
    if pending:
        db.flush()
        return False

    season.status = "finished"
    db.flush()
    _settle(db, season, quotes, now_ms)
    return True


def _settle(db: Session, season: Season, quotes: QuoteBook, now_ms: int) -> None:
    from app.game.leaderboard import award_season_badges
    from app.game.leagues import apply_week_results

    award_season_badges(db, season, quotes, now_ms)
    if season.kind == SeasonKind.WEEK.value:
        apply_week_results(db, season, quotes, now_ms)
