from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.game.analytics import log_event
from app.game.config import STARTER_SYMBOLS
from app.game.errors import InvalidNickname, NicknameTaken
from app.game.models import Player

NICKNAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]{3,16}")


def _default_nickname(tg_user: dict) -> str:
    for key in ("username", "first_name"):
        value = str(tg_user.get(key) or "").strip()
        if value:
            return value[:32]
    return f"player{tg_user['id']}"


def _language(tg_user: dict) -> str:
    return "ru" if str(tg_user.get("language_code") or "").lower().startswith("ru") else "en"


def start_player(db: Session, tg_user: dict, now_ms: int) -> tuple[Player, bool]:
    """Player for a Telegram user and whether this call created it.

    The first visit (bot or Mini App) creates the player with a Telegram-based nickname.
    """
    telegram_id = int(tg_user["id"])
    player = db.query(Player).filter_by(telegram_id=telegram_id).one_or_none()
    if player is not None:
        return player, False

    player = Player(
        telegram_id=telegram_id,
        nickname=_default_nickname(tg_user),
        language=_language(tg_user),
        created_at=now_ms,
    )
    db.add(player)
    try:
        db.flush()
        log_event(db, player, "start", now_ms)
        db.commit()
    except IntegrityError:
        # A parallel first request created the player first.
        db.rollback()
        return db.query(Player).filter_by(telegram_id=telegram_id).one(), False
    return player, True


def get_or_create_player(db: Session, tg_user: dict, now_ms: int) -> Player:
    return start_player(db, tg_user, now_ms)[0]


def validate_nickname(db: Session, player: Player, nickname: str) -> str:
    nickname = (nickname or "").strip()
    if not NICKNAME_RE.fullmatch(nickname):
        raise InvalidNickname(nickname)
    taken = (
        db.query(Player.id)
        .filter(func.lower(Player.nickname) == nickname.lower(), Player.id != player.id)
        .first()
    )
    if taken is not None:
        raise NicknameTaken(nickname)
    return nickname


def unlocked_symbols(player: Player) -> tuple[str, ...]:
    """Pairs the player may trade. Level-based unlocks arrive with lessons (phase 5)."""
    return STARTER_SYMBOLS
