"""Day streak: consecutive UTC days with a trade, a lesson or the daily puzzle, read from events."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.game.analytics import log_event
from app.game.config import DAY_MS, STREAK_KINDS, STREAK_MILESTONES
from app.game.models import Event, Player
from app.game.progress import award_xp

# Longest streak we look back for; older days do not change anything players see.
LOOKBACK_DAYS = 400


def active_days(db: Session, player_id: int, now_ms: int) -> set[int]:
    rows = db.query(Event.created_at).filter(
        Event.player_id == player_id,
        Event.kind.in_(STREAK_KINDS),
        Event.created_at >= now_ms - LOOKBACK_DAYS * DAY_MS,
        Event.created_at <= now_ms,
    )
    return {created_at // DAY_MS for (created_at,) in rows}


def streak_length(days: set[int], today: int) -> tuple[int, bool]:
    """(streak, today_done). A streak that reached yesterday is still alive until today ends."""
    today_done = today in days
    day = today if today_done else today - 1
    length = 0
    while day in days:
        length += 1
        day -= 1
    return length, today_done


def claim_streak(db: Session, player: Player, now_ms: int) -> dict:
    """Streak state for the player; grants milestone XP once per streak run."""
    today = now_ms // DAY_MS
    days, today_done = streak_length(active_days(db, player.id, now_ms), today)
    last_day = today if today_done else today - 1
    streak_start_ms = (last_day - days + 1) * DAY_MS
    xp_awarded = 0
    for target, xp in STREAK_MILESTONES:
        if days < target:
            continue
        kind = f"streak_{target}"
        seen = db.query(Event.id).filter(
            Event.player_id == player.id, Event.kind == kind, Event.created_at >= streak_start_ms
        ).first()
        if seen is None:
            log_event(db, player, kind, now_ms)
            award_xp(player, xp)
            xp_awarded += xp
    upcoming = [target for target, _ in STREAK_MILESTONES if target > days]
    return {
        "days": days,
        "today_done": today_done,
        "next_milestone": upcoming[0] if upcoming else None,
        "xp_awarded": xp_awarded,
    }
