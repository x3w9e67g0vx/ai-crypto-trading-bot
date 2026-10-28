"""Hidden /admin: works only in the owner's private chat (ADMIN_CHAT_ID), silent for everyone else."""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.game.admin import admin_stats, set_banned
from app.game.channel import PREVIEW_KINDS, preview_post
from app.game.config import SeasonKind
from app.game.seasons import end_season_now
from app.i18n.strings import normalize_lang, t
from app.telegram.channel import send_post


def is_admin(message: Message, admin_chat_id: int | None) -> bool:
    return (
        admin_chat_id is not None
        and message.chat.type == "private"
        and message.from_user is not None
        and message.from_user.id == admin_chat_id
    )


async def admin(message: Message, command: CommandObject, session_factory, quotes, clock, bot_username) -> None:
    lang = normalize_lang(message.from_user.language_code)
    args = (command.args or "").split()
    now_ms = clock()
    with session_factory() as db:
        if not args:
            stats = admin_stats(db, now_ms)
            db.commit()
            (d1_kept, d1_total), (d7_kept, d7_total) = stats.pop("d1"), stats.pop("d7")
            text = t("admin.stats", lang=lang, d1_kept=d1_kept, d1_total=d1_total,
                     d7_kept=d7_kept, d7_total=d7_total, **stats)
        elif args[0] in ("ban", "unban") and len(args) == 2:
            player = set_banned(db, args[1], args[0] == "ban")
            db.commit()
            if player is None:
                text = t("admin.not_found", lang=lang, nickname=escape(args[1]))
            else:
                text = t(f"admin.{args[0]}ned", lang=lang, nickname=escape(player.nickname))
        elif args[0] in ("end", "restart") and len(args) == 2 and args[1] in {kind.value for kind in SeasonKind}:
            old, new, done = end_season_now(db, SeasonKind(args[1]), quotes, now_ms, settle=args[0] == "end")
            db.commit()
            text = t("admin.ended", lang=lang, old_id=old.id, kind=old.kind, new_id=new.id,
                     pending="" if done else t("admin.pending", lang=lang))
        elif args[0] == "post" and len(args) == 2 and args[1] in PREVIEW_KINDS:
            # A preview for the owner: nothing is recorded, the channel still gets it on schedule.
            post = preview_post(db, quotes, args[1], now_ms, bot_username)
            db.rollback()
            if post is not None:
                await send_post(message.bot, message.chat.id, post)
                return
            text = t("admin.post_empty", lang=lang)
        else:
            text = t("admin.usage", lang=lang)
    await message.answer(text)


def create_router() -> Router:
    router = Router(name="admin")
    router.message.register(admin, Command("admin"), is_admin)
    return router
