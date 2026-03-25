from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from app.core.config import settings

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    await message.answer(
        "AI Crypto Trading Bot запущен.\nДоступные команды:\n/start\n/status\n/ping"
    )


@dp.message(Command("status"))
async def status_handler(message: Message) -> None:
    await message.answer("Бот работает нормально.")


@dp.message(Command("ping"))
async def ping_handler(message: Message) -> None:
    await message.answer("pong")


async def main() -> None:
    await dp.start_polling(bot)


@dp.message(Command("chatid"))
async def chatid_handler(message: Message) -> None:
    await message.answer(f"Ваш chat_id: {message.chat.id}")


if __name__ == "__main__":
    asyncio.run(main())
