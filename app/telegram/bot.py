"""VEYDRANOX bot: `python -m app.telegram.bot` (polling only).

Quotes come from Postgres (written by `app.worker`); notifications and channel posts run in `app.scheduler`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.client.telegram import PRODUCTION, TelegramAPIServer
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, User

from app.core.config import settings
from app.game.quote_store import run_quote_sync
from app.game.quotes import QuoteBook
from app.i18n.strings import t
from app.telegram import admin, handlers

logger = logging.getLogger(__name__)

PRIVATE_COMMANDS = {
    "ru": [
        ("start", "Начать игру"),
        ("play", "Открыть игру"),
        ("rank", "Мои места в сезонах"),
        ("learn", "Уроки"),
        ("weekend", "Турнир выходных"),
        ("pro", "Pro и косметика за ⭐"),
        ("settings", "Уведомления и язык"),
        ("help", "Справка"),
    ],
    "en": [
        ("start", "Start the game"),
        ("play", "Open the game"),
        ("rank", "My season places"),
        ("learn", "Lessons"),
        ("weekend", "Weekend tournament"),
        ("pro", "Pro and cosmetics for ⭐"),
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
    """Command menus: eight in private chats, /league in groups; /admin stays hidden."""
    for scope, commands in ((BotCommandScopeAllPrivateChats(), PRIVATE_COMMANDS), (BotCommandScopeAllGroupChats(), GROUP_COMMANDS)):
        for lang, items in commands.items():
            menu = [BotCommand(command=name, description=description) for name, description in items]
            await bot.set_my_commands(menu, scope=scope, language_code=None if lang == "en" else lang)
    await bot.set_my_description(t("disclaimer", lang="ru"), language_code="ru")
    await bot.set_my_description(t("disclaimer", lang="en"))


class RetryAfterGate(BaseRequestMiddleware):
    """After a 429, hold every request of this bot until Telegram's retry_after has passed.

    It never resends by itself: callers (aiogram polling, our loops) decide whether to retry,
    so polling's 1-5s backoff can no longer hammer Telegram during flood control.
    """

    def __init__(self, clock=time.monotonic, sleep=asyncio.sleep):
        self.clock, self.sleep, self.until = clock, sleep, 0.0

    async def __call__(self, make_request, bot, method):
        if (wait := self.until - self.clock()) > 0:
            await self.sleep(wait)
        try:
            return await make_request(bot, method)
        except TelegramRetryAfter as e:
            self.until = max(self.until, self.clock() + e.retry_after)
            logger.warning("Telegram 429 on %s, holding requests for %ss", type(method).__name__, e.retry_after)
            raise


def make_bot() -> Bot:
    # aiohttp ignores HTTPS_PROXY, so pass it explicitly when Telegram is reachable only through a proxy.
    proxy = os.getenv("TELEGRAM_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    # TELEGRAM_API_URL points at a local telegram-bot-api server (compose profile `local-bot-api`).
    local = os.getenv("TELEGRAM_API_URL")
    api = TelegramAPIServer.from_base(local, is_local=True) if local else PRODUCTION
    session = AiohttpSession(proxy=proxy, api=api) if proxy else AiohttpSession(api=api)
    session.middleware(RetryAfterGate())
    return Bot(token=settings.TELEGRAM_BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode="HTML"))


async def wait_for_me(bot: Bot, sleep=asyncio.sleep) -> User:
    """getMe until it works. bot.me() caches the result, so start_polling does not call getMe again.

    429: the session gate waits retry_after before the next try. Network errors: exponential pause up to 60s.
    Auth errors (bad token) propagate and stop the process.
    """
    delay = 1
    while True:
        try:
            return await bot.me()
        except TelegramRetryAfter:
            continue
        except TelegramNetworkError as e:
            logger.warning("Telegram unreachable (%s), retry in %ss", e.message, delay)
            await sleep(delay)
            delay = min(delay * 2, 60)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    from app.core.db.session import SessionLocal

    bot = make_bot()
    sync = None
    try:  # one try for the whole life of the bot, so the HTTP session is closed on any exit path
        me = await wait_for_me(bot)
        quotes = QuoteBook()
        dp = build_dispatcher(
            session_factory=SessionLocal,
            quotes=quotes,
            clock=lambda: int(time.time() * 1000),
            bot_username=me.username or "",
            miniapp_url=settings.MINIAPP_URL,
            admin_chat_id=settings.ADMIN_CHAT_ID,
        )
        try:
            await set_commands(bot)
        except TelegramAPIError as e:  # menus are cosmetic; never block polling on them
            logger.warning("set_commands failed: %s", e)
        sync = asyncio.create_task(run_quote_sync(SessionLocal, quotes, publish=False))
        await dp.start_polling(bot)
    finally:
        if sync is not None:
            sync.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
