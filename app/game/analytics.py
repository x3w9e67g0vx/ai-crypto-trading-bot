from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.game.config import DAY_MS
from app.game.models import Event, Player


def _day(ms: int) -> int:
    return ms // DAY_MS


def log_event(db: Session, player: Player, kind: str, now_ms: int, *, once_per_day: bool = False) -> bool:
    """Record an analytics event; with once_per_day a repeat within the UTC day is skipped."""
    if once_per_day:
        day_start = _day(now_ms) * DAY_MS
        seen = (
            db.query(Event.id)
            .filter(Event.player_id == player.id, Event.kind == kind, Event.created_at >= day_start)
            .first()
        )
        if seen is not None:
            return False
    db.add(Event(player_id=player.id, kind=kind, created_at=now_ms))
    db.flush()
    return True


def retention(db: Session, days: int, now_ms: int) -> tuple[int, int]:
    """(retained, cohort) for day N: cohort first started N or more UTC days ago,
    retained ones have any event on the UTC day first_start_day + N."""
    first_starts = (
        db.query(Event.player_id, func.min(Event.created_at))
        .join(Player, Player.id == Event.player_id)
        .filter(Event.kind == "start", Player.is_ai.is_(False))
        .group_by(Event.player_id)
        .all()
    )
    today = _day(now_ms)
    cohort = {player_id: _day(first) + days for player_id, first in first_starts if _day(first) + days <= today}
    if not cohort:
        return 0, 0

    retained = set()
    events = db.query(Event.player_id, Event.created_at).filter(Event.player_id.in_(list(cohort)))
    for player_id, created_at in events:
        if _day(created_at) == cohort[player_id]:
            retained.add(player_id)
    return len(retained), len(cohort)
