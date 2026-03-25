from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.notification_service import NotificationService

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    await message.answer(
        "AI Crypto Trading Bot запущен.\n"
        "Доступные команды:\n"
        "/start\n"
        "/status\n"
        "/ping\n"
        "/chatid\n"
        "/last_signal\n"
        "/portfolio\n"
        "/trades"
    )


@dp.message(Command("status"))
async def status_handler(message: Message) -> None:
    await message.answer("Бот работает нормально.")


@dp.message(Command("ping"))
async def ping_handler(message: Message) -> None:
    await message.answer("pong")


@dp.message(Command("chatid"))
async def chatid_handler(message: Message) -> None:
    await message.answer(f"Ваш chat_id: {message.chat.id}")


@dp.message(Command("last_signal"))
async def last_signal_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_last_signal_message(symbol="BTC/USDT", timeframe="5m")
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("portfolio"))
async def portfolio_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_portfolio_message(symbol="BTC/USDT")
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("trades"))
async def trades_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_recent_trades_message(symbol="BTC/USDT", limit=5)
        await message.answer(text)
    finally:
        db.close()


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
