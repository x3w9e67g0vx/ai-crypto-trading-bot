from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.game.analytics import retention
from app.game.config import DAY_MS, SeasonKind
from app.game.models import Fill, Player, Portfolio
from app.game.seasons import ensure_current_season


def admin_stats(db: Session, now_ms: int) -> dict:
    humans = db.query(Player).filter(Player.is_ai.is_(False))
    week = ensure_current_season(db, SeasonKind.WEEK, now_ms)
    day_start = now_ms - now_ms % DAY_MS
    return {
        "players": humans.count(),
        "new_24h": humans.filter(Player.created_at > now_ms - DAY_MS).count(),
        "d1": retention(db, 1, now_ms),
        "d7": retention(db, 7, now_ms),
        "week_active": db.query(Portfolio)
        .join(Player)
        .filter(Portfolio.season_id == week.id, Portfolio.trades_count > 0, Player.is_ai.is_(False))
        .count(),
        "trades_today": db.query(Fill)
        .join(Portfolio, Fill.portfolio_id == Portfolio.id)
        .join(Player)
        .filter(Fill.is_user.is_(True), Fill.created_at >= day_start, Player.is_ai.is_(False))
        .count(),
    }


def set_banned(db: Session, nickname: str, banned: bool) -> Player | None:
    """Ban or unban a human player by nickname (case-insensitive)."""
    player = (
        db.query(Player)
        .filter(func.lower(Player.nickname) == nickname.strip().lower(), Player.is_ai.is_(False))
        .one_or_none()
    )
    if player is not None:
        player.is_banned = banned
        db.flush()
    return player
