from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.game.models import Badge, Player
from app.game.players import start_player

REF_RE = re.compile(r"ref_(\d+)")


def parse_ref(payload: str | None) -> int | None:
    """Referrer id from a /start payload like `ref_42`."""
    match = REF_RE.fullmatch((payload or "").strip())
    return int(match.group(1)) if match else None


def ref_link(bot_username: str, player: Player) -> str:
    return f"https://t.me/{bot_username}?start=ref_{player.id}"


def apply_referral(db: Session, player: Player, referrer_id: int, now_ms: int) -> bool:
    """Record who invited the player. Pro days for both come with payments;
    on the beta the inviter gets the one-time `recruiter` badge."""
    if player.referred_by_id is not None or referrer_id == player.id:
        return False
    referrer = db.get(Player, referrer_id)
    if referrer is None or referrer.is_ai:
        return False

    player.referred_by_id = referrer.id
    has_badge = db.query(Badge.id).filter_by(player_id=referrer.id, code="recruiter").first()
    if has_badge is None:
        db.add(Badge(player_id=referrer.id, code="recruiter", season_id=None, created_at=now_ms))
    db.flush()
    return True


def register_start(db: Session, tg_user: dict, payload: str | None, now_ms: int) -> tuple[Player, bool]:
    """/start: get or create the player; a referral counts only for a player created right now."""
    player, created = start_player(db, tg_user, now_ms)
    referrer_id = parse_ref(payload)
    if created and referrer_id is not None and apply_referral(db, player, referrer_id, now_ms):
        db.commit()
    return player, created
