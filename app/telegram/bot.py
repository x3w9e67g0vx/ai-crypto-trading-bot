from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.notification_service import NotificationService
from app.services.subscription_service import SubscriptionService

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


def get_help_text() -> str:
    return (
        "AI Crypto Trading Bot\n\n"
        "Команды:\n"
        "/start — старт\n"
        "/help — список команд\n"
        "/status — статус бота\n"
        "/ping — проверка\n"
        "/chatid — показать chat_id\n"
        "/signals — actionable summary по default symbols\n"
        "/scan_all — summary по default symbols, включая HOLD\n"
        "/signal_btc — сигнал по BTC/USDT\n"
        "/signal_eth — сигнал по ETH/USDT\n"
        "/signal_sol — сигнал по SOL/USDT\n"
        "/portfolio — paper portfolio BTC/USDT\n"
        "/trades — последние сделки BTC/USDT\n"
        "/last_signals — последние сохранённые сигналы по default symbols\n"
        "/subscribe_btc — подписаться на BTC/USDT\n"
        "/subscribe_eth — подписаться на ETH/USDT\n"
        "/subscribe_sol — подписаться на SOL/USDT\n"
        "/unsubscribe_btc — отписаться от BTC/USDT\n"
        "/unsubscribe_eth — отписаться от ETH/USDT\n"
        "/unsubscribe_sol — отписаться от SOL/USDT\n"
        "/my_symbols — мои подписки\n"
    )


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    await message.answer(get_help_text())


@dp.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(get_help_text())


@dp.message(Command("status"))
async def status_handler(message: Message) -> None:
    await message.answer("Бот работает нормально.")


@dp.message(Command("ping"))
async def ping_handler(message: Message) -> None:
    await message.answer("pong")


@dp.message(Command("chatid"))
async def chatid_handler(message: Message) -> None:
    await message.answer(f"Ваш chat_id: {message.chat.id}")


@dp.message(Command("signals"))
@dp.message(Command("signals"))
async def signals_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        sub_service = SubscriptionService(db)
        symbols = sub_service.get_symbols_for_chat(message.chat.id)

        if not symbols:
            symbols = settings.get_default_symbols()

        service = NotificationService(db)
        should_send, text = service.format_multi_symbol_signals_summary(
            symbols=symbols,
            timeframe="5m",
            model_type="logistic_regression",
            actionable_only=True,
        )

        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("scan_all"))
async def scan_all_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        sub_service = SubscriptionService(db)
        symbols = sub_service.get_symbols_for_chat(message.chat.id)

        if not symbols:
            symbols = settings.get_default_symbols()

        service = NotificationService(db)
        _, text = service.format_multi_symbol_signals_summary(
            symbols=symbols,
            timeframe="5m",
            model_type="logistic_regression",
            actionable_only=False,
        )

        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_btc"))
async def signal_btc_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="BTC/USDT",
            timeframe="5m",
            model_type="logistic_regression",
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_eth"))
async def signal_eth_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="ETH/USDT",
            timeframe="5m",
            model_type="logistic_regression",
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_sol"))
async def signal_sol_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="SOL/USDT",
            timeframe="5m",
            model_type="logistic_regression",
        )
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


@dp.message(Command("last_signals"))
async def last_signals_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        sub_service = SubscriptionService(db)
        symbols = sub_service.get_symbols_for_chat(message.chat.id)

        if not symbols:
            symbols = settings.get_default_symbols()

        service = NotificationService(db)
        text = service.format_recent_signals_summary(
            symbols=symbols,
            timeframe="5m",
            limit_per_symbol=3,
        )

        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("subscribe_btc"))
async def subscribe_btc_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = SubscriptionService(db)
        result = service.subscribe(chat_id=message.chat.id, symbol="BTC/USDT")
        await message.answer(f"{result['message']}: BTC/USDT")
    finally:
        db.close()


@dp.message(Command("subscribe_eth"))
async def subscribe_eth_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = SubscriptionService(db)
        result = service.subscribe(chat_id=message.chat.id, symbol="ETH/USDT")
        await message.answer(f"{result['message']}: ETH/USDT")
    finally:
        db.close()


@dp.message(Command("subscribe_sol"))
async def subscribe_sol_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = SubscriptionService(db)
        result = service.subscribe(chat_id=message.chat.id, symbol="SOL/USDT")
        await message.answer(f"{result['message']}: SOL/USDT")
    finally:
        db.close()


@dp.message(Command("unsubscribe_btc"))
async def unsubscribe_btc_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = SubscriptionService(db)
        result = service.unsubscribe(chat_id=message.chat.id, symbol="BTC/USDT")
        await message.answer(f"{result['message']}: BTC/USDT")
    finally:
        db.close()


@dp.message(Command("unsubscribe_eth"))
async def unsubscribe_eth_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = SubscriptionService(db)
        result = service.unsubscribe(chat_id=message.chat.id, symbol="ETH/USDT")
        await message.answer(f"{result['message']}: ETH/USDT")
    finally:
        db.close()


@dp.message(Command("unsubscribe_sol"))
async def unsubscribe_sol_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = SubscriptionService(db)
        result = service.unsubscribe(chat_id=message.chat.id, symbol="SOL/USDT")
        await message.answer(f"{result['message']}: SOL/USDT")
    finally:
        db.close()


@dp.message(Command("my_symbols"))
async def my_symbols_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = SubscriptionService(db)
        result = service.get_all_for_chat(chat_id=message.chat.id)

        if not result["symbols"]:
            await message.answer("У вас пока нет подписок.")
            return

        symbols_text = "\n".join(f"- {symbol}" for symbol in result["symbols"])
        await message.answer(f"Ваши подписки:\n{symbols_text}")
    finally:
        db.close()


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
