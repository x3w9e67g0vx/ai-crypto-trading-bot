"""Player commands. Six work in private chats only; /league is the group command.

Dependencies come from the dispatcher's workflow data: session_factory, quotes,
clock (() -> ms), bot_username, miniapp_url.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, User

from app.game.chat_leagues import ensure_chat_league, join_chat_league
from app.game.models import ChatLeague
from app.game.players import start_player
from app.game.referrals import register_start
from app.i18n.strings import normalize_lang, t
from app.telegram import views

PRIVATE = F.chat.type == "private"
GROUP = F.chat.type.in_({"group", "supergroup"})


def tg_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "language_code": user.language_code,
    }


async def _edit(message: Message, text: str, reply_markup) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        # "message is not modified" when nothing changed since the last refresh.
        pass


async def start(message: Message, command: CommandObject, session_factory, clock, miniapp_url: str) -> None:
    with session_factory() as db:
        player, _ = register_start(db, tg_user(message.from_user), command.args, clock())
        if player.is_banned:
            await message.answer(t("banned", lang=player.language))
            return
        text, keyboard = views.start_view(player, miniapp_url)
    await message.answer(text, reply_markup=keyboard)


async def play(message: Message, session_factory, clock, miniapp_url: str) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        if player.is_banned:
            await message.answer(t("banned", lang=player.language))
            return
        text, keyboard = views.play_view(player, miniapp_url)
    await message.answer(text, reply_markup=keyboard)


async def rank(message: Message, session_factory, quotes, clock, bot_username: str) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        if player.is_banned:
            await message.answer(t("banned", lang=player.language))
            return
        text = views.rank_view(db, player, quotes, clock(), bot_username)
        db.commit()
    await message.answer(text, disable_web_page_preview=True)


async def learn(message: Message, session_factory, clock) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        lang = player.language
    await message.answer(t("learn.soon", lang=lang))


async def help_command(message: Message, session_factory, clock) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        lang = player.language
    await message.answer(views.help_view(lang))


async def settings_command(message: Message, session_factory, clock) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        text, keyboard = views.settings_view(player)
    await message.answer(text, reply_markup=keyboard)


async def settings_toggle(callback: CallbackQuery, session_factory, clock) -> None:
    option = callback.data.removeprefix("set:")
    with session_factory() as db:
        player, _ = start_player(db, tg_user(callback.from_user), clock())
        if option == "lang":
            player.language = "en" if player.language == "ru" else "ru"
        elif option in views.NOTIFY_FLAGS:
            setattr(player, option, not getattr(player, option))
        db.commit()
        text, keyboard = views.settings_view(player)
    await callback.answer()
    if callback.message is not None:
        await _edit(callback.message, text, keyboard)


async def league_private(message: Message) -> None:
    await message.answer(t("league.private", lang=normalize_lang(message.from_user.language_code)))


async def league_group(message: Message, session_factory, quotes, clock) -> None:
    lang = normalize_lang(message.from_user.language_code if message.from_user else None)
    with session_factory() as db:
        league = ensure_chat_league(db, message.chat.id, message.chat.title or str(message.chat.id), clock())
        text, keyboard = views.league_view(db, league, quotes, clock(), lang)
        db.commit()
    await message.answer(text, reply_markup=keyboard)


async def league_callback(callback: CallbackQuery, session_factory, quotes, clock) -> None:
    _, action, league_id = callback.data.split(":", 2)
    lang = normalize_lang(callback.from_user.language_code)
    with session_factory() as db:
        league = db.get(ChatLeague, int(league_id)) if league_id.isdigit() else None
        if league is None:
            await callback.answer()
            return
        notice = None
        if action == "join":
            player, _ = start_player(db, tg_user(callback.from_user), clock())
            if player.is_banned:
                notice = t("banned", lang=player.language)
            else:
                joined = join_chat_league(db, league, player, clock())
                notice = t("league.joined" if joined else "league.already", lang=player.language)
        text, keyboard = views.league_view(db, league, quotes, clock(), lang)
        db.commit()
    await callback.answer(notice, show_alert=notice is not None)
    if callback.message is not None:
        await _edit(callback.message, text, keyboard)


def create_router() -> Router:
    router = Router(name="game")
    router.message.register(start, CommandStart(), PRIVATE)
    router.message.register(play, Command("play"), PRIVATE)
    router.message.register(rank, Command("rank"), PRIVATE)
    router.message.register(learn, Command("learn"), PRIVATE)
    router.message.register(help_command, Command("help"), PRIVATE)
    router.message.register(settings_command, Command("settings"), PRIVATE)
    router.callback_query.register(settings_toggle, F.data.startswith("set:"))
    router.message.register(league_private, Command("league"), PRIVATE)
    router.message.register(league_group, Command("league"), GROUP)
    router.callback_query.register(league_callback, F.data.startswith("league:"))
    return router
