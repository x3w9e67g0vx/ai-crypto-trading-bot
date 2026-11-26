"""Weekend tournament: a `weekend` season from Saturday to Monday 00:00 UTC.

Players sign up in the bot any time that week; trading opens on Saturday.
Top 3 get Pro days and the cup badge, beat_ai comes from the usual season badges."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.game.analytics import log_event
from app.game.config import DAY_MS, WEEK_MS, WEEKEND_KIND, WEEKEND_PRO_DAYS, SeasonKind
from app.game.leaderboard import prize_eligible, standings
from app.game.models import Badge, Player, Portfolio, Season
from app.game.quotes import QuoteBook
from app.game.seasons import join_season, season_bounds
from app.game.shop import extend_pro

CUP_BADGE = "weekend_cup"


def weekend_bounds(now_ms: int) -> tuple[int, int]:
    """This calendar week's weekend; from Monday 00:00 UTC that is the coming one."""
    monday, _ = season_bounds(SeasonKind.WEEK, now_ms)
    return monday + 5 * DAY_MS, monday + WEEK_MS


def ensure_weekend(db: Session, now_ms: int) -> Season:
    starts_at, ends_at = weekend_bounds(now_ms)
    season = db.query(Season).filter_by(kind=WEEKEND_KIND, starts_at=starts_at).first()
    if season is None:
        season = Season(kind=WEEKEND_KIND, starts_at=starts_at, ends_at=ends_at, status="active")
        db.add(season)
        db.flush()
    return season


def live_weekend(db: Session, now_ms: int) -> Season | None:
    """The tournament while trading is open."""
    season = ensure_weekend(db, now_ms)
    return season if season.status == "active" and season.starts_at <= now_ms < season.ends_at else None


def register(db: Session, player: Player, now_ms: int) -> Portfolio:
    """Sign up for this week's tournament; again is a no-op. SeasonClosed for banned players."""
    season = ensure_weekend(db, now_ms)
    joined = db.query(Portfolio.id).filter_by(player_id=player.id, season_id=season.id).first() is not None
    portfolio = join_season(db, player, season, now_ms)
    if not joined:
        log_event(db, player, "weekend_join", now_ms)
    return portfolio


def weekend_portfolio(db: Session, player: Player, now_ms: int) -> Portfolio | None:
    season = live_weekend(db, now_ms)
    if season is None:
        return None
    return db.query(Portfolio).filter_by(player_id=player.id, season_id=season.id).one_or_none()


def weekend_info(db: Session, player: Player, now_ms: int) -> dict:
    season = ensure_weekend(db, now_ms)
    joined = db.query(Portfolio.id).filter_by(player_id=player.id, season_id=season.id).first() is not None
    return {"starts_at": season.starts_at, "ends_at": season.ends_at, "joined": joined}


def registered_count(db: Session, season: Season) -> int:
    return db.query(Portfolio).join(Player).filter(Portfolio.season_id == season.id, Player.is_ai.is_(False)).count()


def award_weekend_prizes(db: Session, season: Season, quotes: QuoteBook, now_ms: int) -> list[Badge]:
    """Places 1-3 among prize-eligible players: Pro days and the cup badge."""
    winners = prize_eligible(db, season, standings(db, season, quotes, now_ms), now_ms)[: len(WEEKEND_PRO_DAYS)]
    badges = []
    for row, days in zip(winners, WEEKEND_PRO_DAYS):
        extend_pro(db.get(Player, row.player_id), days, now_ms)
        badges.append(Badge(player_id=row.player_id, code=CUP_BADGE, season_id=season.id, created_at=now_ms))
    db.add_all(badges)
    db.flush()
    return badges
