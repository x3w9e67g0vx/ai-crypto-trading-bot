from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.game.config import (
    DAY_MS,
    LEAGUE_FULL_MOVE,
    LEAGUE_GROUP_SIZE,
    LEAGUE_SMALL_SHARE,
    LEAGUE_TIERS,
    MIN_QUALIFYING_TRADES,
)
from app.game.leaderboard import standings
from app.game.models import LeagueGroup, LeagueMembership, Player, Portfolio, Season
from app.game.quotes import QuoteBook


def _group_sizes(db: Session, season: Season, tier: str) -> list[tuple[LeagueGroup, int]]:
    rows = (
        db.query(LeagueGroup, func.count(LeagueMembership.id))
        .outerjoin(LeagueMembership, LeagueMembership.group_id == LeagueGroup.id)
        .filter(LeagueGroup.season_id == season.id, LeagueGroup.tier == tier)
        .group_by(LeagueGroup.id)
        .order_by(LeagueGroup.number)
        .all()
    )
    return [(group, size) for group, size in rows]


def assign_group(db: Session, portfolio: Portfolio, season: Season, now_ms: int) -> LeagueGroup:
    """Fill groups of the player's tier in join order; new groups only open on the first day."""
    tier = portfolio.player.league_tier
    groups = _group_sizes(db, season, tier)
    group = next((group for group, size in groups if size < LEAGUE_GROUP_SIZE), None)
    if group is None:
        if not groups or now_ms - season.starts_at < DAY_MS:
            group = LeagueGroup(season_id=season.id, tier=tier, number=len(groups) + 1)
            db.add(group)
            db.flush()
        else:
            group = min(groups, key=lambda item: item[1])[0]
    db.add(LeagueMembership(group_id=group.id, portfolio_id=portfolio.id, joined_at=now_ms))
    db.flush()
    return group


def group_portfolio_ids(db: Session, portfolio: Portfolio) -> tuple[LeagueGroup | None, list[int] | None]:
    """The portfolio's week league group and its members; (None, None) outside leagues."""
    group = (
        db.query(LeagueGroup)
        .join(LeagueMembership, LeagueMembership.group_id == LeagueGroup.id)
        .filter(LeagueMembership.portfolio_id == portfolio.id)
        .one_or_none()
    )
    if group is None:
        return None, None
    ids = [portfolio_id for (portfolio_id,) in db.query(LeagueMembership.portfolio_id).filter_by(group_id=group.id)]
    return group, ids


def movement_count(group_size: int, qualified: int) -> int:
    if group_size >= LEAGUE_GROUP_SIZE:
        return LEAGUE_FULL_MOVE
    if qualified < MIN_QUALIFYING_TRADES:
        return 0
    return max(1, int(qualified * LEAGUE_SMALL_SHARE))


def compute_movements(ranked_qualified: list[int], group_size: int) -> tuple[list[int], list[int]]:
    """Return (promoted, demoted) player ids from a best-first list of qualified humans."""
    count = min(movement_count(group_size, len(ranked_qualified)), len(ranked_qualified) // 2)
    if count == 0:
        return [], []
    return ranked_qualified[:count], ranked_qualified[-count:]


def _shift(tier: str, step: int) -> str:
    index = LEAGUE_TIERS.index(tier) + step
    return LEAGUE_TIERS[min(max(index, 0), len(LEAGUE_TIERS) - 1)]


def apply_week_results(db: Session, season: Season, quotes: QuoteBook, now_ms: int) -> None:
    new_tiers: dict[int, str] = {}
    for group in db.query(LeagueGroup).filter_by(season_id=season.id):
        member_ids = [
            membership.portfolio_id
            for membership in db.query(LeagueMembership).filter_by(group_id=group.id)
        ]
        rows = standings(db, season, quotes, now_ms, portfolio_ids=member_ids)
        ranked = [row.player_id for row in rows if row.qualified and not row.is_ai]
        promoted, demoted = compute_movements(ranked, len(member_ids))
        for player_id in promoted:
            new_tiers[player_id] = _shift(group.tier, 1)
        for player_id in demoted:
            new_tiers[player_id] = _shift(group.tier, -1)

    # Players who did not trade at all this week drop one league.
    active_ids = {
        player_id
        for (player_id,) in db.query(Portfolio.player_id).filter(
            Portfolio.season_id == season.id, Portfolio.trades_count > 0
        )
    }
    for player in db.query(Player).filter(Player.is_ai.is_(False), Player.league_tier != LEAGUE_TIERS[0]):
        if player.id not in active_ids and player.id not in new_tiers:
            new_tiers[player.id] = _shift(player.league_tier, -1)

    for player in db.query(Player).filter(Player.id.in_(list(new_tiers))):
        player.league_tier = new_tiers[player.id]
    db.flush()
