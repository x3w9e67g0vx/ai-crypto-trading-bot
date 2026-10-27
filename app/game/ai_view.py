from __future__ import annotations

from sqlalchemy.orm import Session

from app.game.config import AI_VISIBILITY_DELAY_MS
from app.game.models import Player, Portfolio, Position


def is_pro(player: Player, now_ms: int) -> bool:
    return player.is_pro_until is not None and player.is_pro_until > now_ms


def ai_positions_view(db: Session, viewer: Player, ai_portfolio: Portfolio, now_ms: int) -> list[Position]:
    """AI positions the viewer may see: live for Pro, otherwise as they
    stood an hour ago (a position closed since then still shows as open)."""
    as_of = now_ms if is_pro(viewer, now_ms) else now_ms - AI_VISIBILITY_DELAY_MS
    return (
        db.query(Position)
        .filter(
            Position.portfolio_id == ai_portfolio.id,
            Position.opened_at <= as_of,
            Position.closed_at.is_(None) | (Position.closed_at > as_of),
        )
        .order_by(Position.opened_at)
        .all()
    )
