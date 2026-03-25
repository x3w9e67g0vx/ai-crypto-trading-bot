from __future__ import annotations

from aiogram import Bot

from app.core.config import settings


class TelegramService:
    def __init__(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

        self.bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    async def send_message(self, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text)
