"""Player commands. Seven work in private chats only; /league is the group command.

Dependencies come from the dispatcher's workflow data: session_factory, quotes,
clock (() -> ms), bot_username, miniapp_url.
"""

from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery, User

from app.game.chat_leagues import ensure_chat_league, join_chat_league
from app.game.models import ChatLeague
from app.game.players import start_player
from app.game.duels import accept_duel, parse_duel
from app.game.errors import DuelBusy, DuelNotFound, DuelOwn
from app.game.referrals import apply_referral, register_start
from app.game.shop import ITEMS, check_purchase, grant
from app.i18n.strings import normalize_lang, t
from app.telegram import views

logger = logging.getLogger(__name__)

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
    duel_id = parse_duel(command.args)
    with session_factory() as db:
        now_ms = clock()
        player, created = register_start(db, tg_user(message.from_user), command.args, now_ms)
        if player.is_banned:
            await message.answer(t("banned", lang=player.language))
            return
        if duel_id is not None:
            text, notice = _accept_duel(db, player, duel_id, created, now_ms)
            await message.answer(text, reply_markup=views.play_keyboard(player.language, miniapp_url))
            if notice is not None:
                try:
                    await message.bot.send_message(*notice)
                except Exception:
                    logger.warning("duel accept notice failed", exc_info=True)
            return
        text, keyboard = views.start_view(player, miniapp_url)
    await message.answer(text, reply_markup=keyboard)


def _accept_duel(db, player, duel_id: int, created: bool, now_ms: int) -> tuple[str, tuple[int, str] | None]:
    """Reply text for the accepting player and (chat_id, text) for the challenger, if any."""
    lang = player.language
    try:
        duel = accept_duel(db, duel_id, player, now_ms)
    except DuelOwn:
        return t("duel.own", lang=lang), None
    except DuelBusy:
        return t("duel.busy", lang=lang), None
    except DuelNotFound:
        return t("duel.not_found", lang=lang), None
    if created:
        apply_referral(db, player, duel.challenger_id, now_ms)
    db.commit()
    ends = time.strftime("%H:%M", time.gmtime(duel.season.ends_at / 1000))
    challenger = duel.challenger
    notice = None
    if challenger.telegram_id is not None:
        notice = (challenger.telegram_id, t("duel.accepted", lang=challenger.language, rival=player.nickname, ends=ends))
    return t("duel.started", lang=lang, rival=challenger.nickname, ends=ends), notice


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


async def learn(message: Message, session_factory, clock, miniapp_url: str) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        if player.is_banned:
            await message.answer(t("banned", lang=player.language))
            return
        text, keyboard = views.learn_view(db, player, miniapp_url)
    await message.answer(text, reply_markup=keyboard)


async def help_command(message: Message, session_factory, clock) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        lang = player.language
    await message.answer(views.help_view(lang))


async def settings_command(message: Message, session_factory, clock) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        if player.is_banned:
            await message.answer(t("banned", lang=player.language))
            return
        text, keyboard = views.settings_view(player)
    await message.answer(text, reply_markup=keyboard)


async def settings_toggle(callback: CallbackQuery, session_factory, clock) -> None:
    option = callback.data.removeprefix("set:")
    with session_factory() as db:
        player, _ = start_player(db, tg_user(callback.from_user), clock())
        if player.is_banned:
            await callback.answer(t("banned", lang=player.language), show_alert=True)
            return
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
        # Callback data comes from the client: only the league of this very chat counts.
        if league is None or callback.message is None or league.chat_id != callback.message.chat.id:
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


async def shop_command(message: Message, session_factory, clock) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        if player.is_banned:
            await message.answer(t("banned", lang=player.language))
            return
        text, keyboard = views.shop_view(player, clock())
    await message.answer(text, reply_markup=keyboard)


async def buy_callback(callback: CallbackQuery, session_factory, clock) -> None:
    item = ITEMS.get(callback.data.removeprefix("buy:"))
    with session_factory() as db:
        player, _ = start_player(db, tg_user(callback.from_user), clock())
        lang = player.language
    if item is None or item.stars is None or callback.message is None or player.is_banned:
        await callback.answer()
        return
    await callback.answer()
    title = t(f"item.{item.code}", lang=lang)
    # Stars invoices: currency XTR, no provider token.
    await callback.message.answer_invoice(
        title=title,
        description=title,
        payload=item.code,
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=item.stars)],
    )


async def pre_checkout(query: PreCheckoutQuery, session_factory, clock) -> None:
    with session_factory() as db:
        player, _ = start_player(db, tg_user(query.from_user), clock())
        ok = not player.is_banned and check_purchase(
            db, player, query.invoice_payload, query.currency, query.total_amount
        )
        lang = player.language
    await query.answer(ok=ok, error_message=None if ok else t("shop.declined", lang=lang))


async def paid(message: Message, session_factory, clock) -> None:
    payment = message.successful_payment
    with session_factory() as db:
        player, _ = start_player(db, tg_user(message.from_user), clock())
        grant(db, player, payment.invoice_payload, payment.total_amount, payment.telegram_payment_charge_id, clock())
        db.commit()
        text = t("shop.thanks", lang=player.language, item=t(f"item.{payment.invoice_payload}", lang=player.language))
    await message.answer(text)


def create_router() -> Router:
    router = Router(name="game")
    router.message.register(shop_command, CommandStart(deep_link=True, magic=F.args == "pro"), PRIVATE)
    router.message.register(start, CommandStart(), PRIVATE)
    router.message.register(shop_command, Command("pro"), PRIVATE)
    router.callback_query.register(buy_callback, F.data.startswith("buy:"))
    router.pre_checkout_query.register(pre_checkout)
    router.message.register(paid, F.successful_payment)
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
