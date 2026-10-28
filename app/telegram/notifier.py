from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot

from app.game.notifications import Outgoing, collect_notifications
from app.game.quotes import QuoteBook
from app.i18n.strings import t

logger = logging.getLogger(__name__)

NOTIFY_INTERVAL_S = 60


def render(item: Outgoing) -> str:
    lang = item.player.language
    params = dict(item.params)
    if item.kind == "season_end":
        params["season"] = t(f"season.{params.pop('season_kind')}", lang=lang)
    if item.kind == "ai_open":
        params["side"] = t(f"side.{params['side']}", lang=lang)
    return f"{t(f'notify.{item.kind}', lang=lang, **params)}\n\n{t('notify.footer', lang=lang)}"


async def notify_once(bot: Bot, session_factory, quotes: QuoteBook, now_ms: int) -> int:
    """Send due notifications; returns how many were delivered.

    They are committed before sending, so a crash or a blocked bot never causes repeats.
    """
    with session_factory() as db:
        outgoing = collect_notifications(db, quotes, now_ms)
        messages = [(item.player.telegram_id, render(item)) for item in outgoing]
        db.commit()
    delivered = 0
    for chat_id, text in messages:
        try:
            await bot.send_message(chat_id, text)
            delivered += 1
        except Exception:
            logger.warning("notification to %s failed", chat_id, exc_info=True)
    return delivered


async def run_notifier(bot: Bot, session_factory, quotes: QuoteBook) -> None:
    while True:
        try:
            await notify_once(bot, session_factory, quotes, int(time.time() * 1000))
        except Exception:
            logger.exception("notifier pass failed")
        await asyncio.sleep(NOTIFY_INTERVAL_S)
