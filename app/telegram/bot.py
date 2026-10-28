"""VEYDRANOX bot: `python -m app.telegram.bot`.

The bot runs its own Binance feed (GAME_PRICE_FEED=0 turns it off) for /rank,
notifications and admin season ends; a shared price worker comes in phase 7.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from app.core.config import settings
from app.game.price_feed import BinanceFeed
from app.game.quotes import QuoteBook
from app.i18n.strings import t
from app.telegram import admin, handlers
from app.telegram.notifier import run_notifier

logger = logging.getLogger(__name__)

PRIVATE_COMMANDS = {
    "ru": [
        ("start", "Начать игру"),
        ("play", "Открыть игру"),
        ("rank", "Мои места в сезонах"),
        ("learn", "Уроки"),
        ("settings", "Уведомления и язык"),
        ("help", "Справка"),
    ],
    "en": [
        ("start", "Start the game"),
        ("play", "Open the game"),
        ("rank", "My season places"),
        ("learn", "Lessons"),
        ("settings", "Notifications and language"),
        ("help", "Help"),
    ],
}
GROUP_COMMANDS = {"ru": [("league", "Лига этого чата")], "en": [("league", "This chat's league")]}


def build_dispatcher(
    *,
    session_factory,
    quotes: QuoteBook,
    clock,
    bot_username: str,
    miniapp_url: str,
    admin_chat_id: int | None,
) -> Dispatcher:
    dp = Dispatcher(
        session_factory=session_factory,
        quotes=quotes,
        clock=clock,
        bot_username=bot_username,
        miniapp_url=miniapp_url,
        admin_chat_id=admin_chat_id,
    )
    dp.include_router(admin.create_router())
    dp.include_router(handlers.create_router())
    return dp


async def set_commands(bot: Bot) -> None:
    """Command menus: six in private chats, /league in groups; /admin stays hidden."""
    for scope, commands in ((BotCommandScopeAllPrivateChats(), PRIVATE_COMMANDS), (BotCommandScopeAllGroupChats(), GROUP_COMMANDS)):
        for lang, items in commands.items():
            menu = [BotCommand(command=name, description=description) for name, description in items]
            await bot.set_my_commands(menu, scope=scope, language_code=None if lang == "en" else lang)
    await bot.set_my_description(t("disclaimer", lang="ru"), language_code="ru")
    await bot.set_my_description(t("disclaimer", lang="en"))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    from app.core.db.session import SessionLocal

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    quotes = QuoteBook()
    me = await bot.get_me()
    dp = build_dispatcher(
        session_factory=SessionLocal,
        quotes=quotes,
        clock=lambda: int(time.time() * 1000),
        bot_username=me.username or "",
        miniapp_url=settings.MINIAPP_URL,
        admin_chat_id=settings.ADMIN_CHAT_ID,
    )
    await set_commands(bot)

    tasks = [asyncio.create_task(run_notifier(bot, SessionLocal, quotes))]
    feed = None
    if os.getenv("GAME_PRICE_FEED", "1").strip() != "0":
        feed = BinanceFeed(quotes)
        tasks.append(asyncio.create_task(feed.run()))
    try:
        await dp.start_polling(bot)
    finally:
        if feed is not None:
            feed.stop()
        for task in tasks:
            task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
