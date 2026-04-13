from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.market_data_service import MarketDataService
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
        "/available_symbols — доступные торговые пары\n"
        "/find <text> — найти пары, например /find BTC\n"
        "/signals — actionable summary по default symbols\n"
        "/scan_all — summary по default symbols, включая HOLD\n"
        "/signal_btc — сигнал по BTC/USDT\n"
        "/signal_eth — сигнал по ETH/USDT\n"
        "/signal_sol — сигнал по SOL/USDT\n"
        "/signal_btc_lstm — сигнал LSTM по BTC/USDT\n"
        "/signal_eth_lstm — сигнал LSTM по ETH/USDT\n"
        "/signal_sol_lstm — сигнал LSTM по SOL/USDT\n"
        "/signal_btc_auto — авто-сигнал по BTC/USDT\n"
        "/signal_eth_auto — авто-сигнал по ETH/USDT\n"
        "/signal_sol_auto — авто-сигнал по SOL/USDT\n"
        "/signal <symbol> — сигнал по паре, например /signal BTC/USDT\n"
        "/profile <symbol> — активный профиль пары, например /profile BTC/USDT\n"
        "/set_model <symbol> <model> — сменить модель, например /set_model BTC/USDT lstm\n"
        "/signals_auto — actionable summary через auto profiles\n"
        "/scan_all_auto — summary через auto profiles, включая HOLD\n"
        "/signals_lstm — actionable summary по default symbols через LSTM\n"
        "/scan_all_lstm — summary по default symbols через LSTM, включая HOLD\n"
        "/portfolio — paper portfolio BTC/USDT\n"
        "/trades — последние сделки BTC/USDT\n"
        "/last_signals — последние сохранённые сигналы по default symbols\n"
        "/subscribe <symbol> — подписаться, например /subscribe BTC/USDT\n"
        "/unsubscribe <symbol> — отписаться, например /unsubscribe ETH/USDT\n"
        "/subscribe_btc — подписаться на BTC/USDT\n"
        "/subscribe_eth — подписаться на ETH/USDT\n"
        "/subscribe_sol — подписаться на SOL/USDT\n"
        "/unsubscribe_btc — отписаться от BTC/USDT\n"
        "/unsubscribe_eth — отписаться от ETH/USDT\n"
        "/unsubscribe_sol — отписаться от SOL/USDT\n"
        "/my_symbols — мои подписки\n"
        "/profile_btc — активный профиль BTC/USDT\n"
        "/profile_eth — активный профиль ETH/USDT\n"
        "/profile_sol — активный профиль SOL/USDT\n"
        "/set_btc_lstm — переключить BTC/USDT на LSTM\n"
        "/set_btc_rf — переключить BTC/USDT на Random Forest\n"
        "/set_eth_rf — переключить ETH/USDT на Random Forest\n"
        "/set_sol_rf — переключить SOL/USDT на Random Forest\n"
    )


def normalize_symbol_input(raw: str) -> str:
    value = raw.strip().upper()

    if "/" not in value:
        value = f"{value}/USDT"

    return value


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


@dp.message(Command("subscribe"))
async def subscribe_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        parts = (message.text or "").split(maxsplit=1)

        if len(parts) < 2:
            await message.answer(
                "Укажи символ. Пример:\n"
                "/subscribe BTC\n"
                "/subscribe ETH\n"
                "/subscribe AAVE/USDT"
            )
            return

        symbol = normalize_symbol_input(parts[1])

        market_service = MarketDataService()
        available_symbols = market_service.get_available_symbols(
            quote="USDT",
            only_active=True,
            spot_only=True,
            limit=1000,
        )

        if symbol not in available_symbols:
            preview = "\n".join(f"- {s}" for s in available_symbols[:20])
            await message.answer(
                f"Символ не поддерживается или не найден: {symbol}\n\n"
                f"Примеры доступных символов:\n{preview}"
            )
            return

        service = SubscriptionService(db)
        result = service.subscribe(chat_id=message.chat.id, symbol=symbol)
        await message.answer(f"{result['message']}: {symbol}")
    finally:
        db.close()


@dp.message(Command("unsubscribe"))
async def unsubscribe_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        parts = (message.text or "").split(maxsplit=1)

        if len(parts) < 2:
            await message.answer(
                "Укажи символ. Пример:\n"
                "/unsubscribe BTC/USDT\n"
                "/unsubscribe ETH\n"
                "/unsubscribe SOL"
            )
            return

        symbol = normalize_symbol_input(parts[1])

        service = SubscriptionService(db)
        result = service.unsubscribe(chat_id=message.chat.id, symbol=symbol)
        await message.answer(f"{result['message']}: {symbol}")
    finally:
        db.close()


@dp.message(Command("available_symbols"))
async def available_symbols_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        market_service = MarketDataService()
        service = NotificationService(db)

        symbols = market_service.get_available_symbols(
            quote="USDT",
            only_active=True,
            spot_only=True,
            limit=30,
        )

        text = service.format_available_symbols_message(
            symbols=symbols,
            quote="USDT",
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("find"))
async def find_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        parts = (message.text or "").split(maxsplit=1)

        if len(parts) < 2:
            await message.answer(
                "Укажи текст для поиска. Пример:\n/find BTC\n/find AAVE\n/find DOGE"
            )
            return

        query = parts[1].strip()

        market_service = MarketDataService()
        service = NotificationService(db)

        symbols = market_service.search_symbols(
            query=query,
            quote="USDT",
            only_active=True,
            spot_only=True,
            limit=20,
        )

        text = service.format_symbol_search_message(
            query=query,
            symbols=symbols,
        )
        await message.answer(text)
    finally:
        db.close()


async def main() -> None:
    await dp.start_polling(bot)


@dp.message(Command("signals_lstm"))
async def signals_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        _, text = service.format_multi_symbol_signals_summary(
            symbols=settings.get_default_symbols(),
            timeframe="5m",
            model_type="lstm",
            actionable_only=True,
            use_trend_filter=False,
            use_rsi_filter=False,
            buy_threshold=0.55,
            sell_threshold=0.2,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("scan_all_lstm"))
async def scan_all_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        _, text = service.format_multi_symbol_signals_summary(
            symbols=settings.get_default_symbols(),
            timeframe="5m",
            model_type="lstm",
            actionable_only=False,
            use_trend_filter=False,
            use_rsi_filter=False,
            buy_threshold=0.55,
            sell_threshold=0.2,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_btc_lstm"))
async def signal_btc_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="BTC/USDT",
            timeframe="5m",
            model_type="lstm",
            use_trend_filter=False,
            use_rsi_filter=False,
            buy_threshold=0.55,
            sell_threshold=0.2,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_eth_lstm"))
async def signal_eth_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="ETH/USDT",
            timeframe="5m",
            model_type="lstm",
            use_trend_filter=False,
            use_rsi_filter=False,
            buy_threshold=0.55,
            sell_threshold=0.2,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_sol_lstm"))
async def signal_sol_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="SOL/USDT",
            timeframe="5m",
            model_type="lstm",
            use_trend_filter=False,
            use_rsi_filter=False,
            buy_threshold=0.55,
            sell_threshold=0.2,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signals_auto"))
async def signals_auto_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        _, text = service.format_multi_symbol_signals_summary(
            symbols=settings.get_default_symbols(),
            timeframe="5m",
            model_type="auto",
            actionable_only=True,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("scan_all_auto"))
async def scan_all_auto_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        _, text = service.format_multi_symbol_signals_summary(
            symbols=settings.get_default_symbols(),
            timeframe="5m",
            model_type="auto",
            actionable_only=False,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_btc_auto"))
async def signal_btc_auto_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="BTC/USDT",
            timeframe="5m",
            model_type="auto",
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_eth_auto"))
async def signal_eth_auto_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="ETH/USDT",
            timeframe="5m",
            model_type="auto",
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signal_sol_auto"))
async def signal_sol_auto_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol="SOL/USDT",
            timeframe="5m",
            model_type="auto",
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("profile_btc"))
async def profile_btc_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_strategy_profile_message("BTC/USDT")
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("profile_eth"))
async def profile_eth_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_strategy_profile_message("ETH/USDT")
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("profile_sol"))
async def profile_sol_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_strategy_profile_message("SOL/USDT")
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("set_btc_lstm"))
async def set_btc_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.update_symbol_profile(
            symbol="BTC/USDT",
            model_type="lstm",
            buy_threshold=0.55,
            sell_threshold=0.2,
            use_trend_filter=False,
            use_rsi_filter=False,
            target_threshold=0.002,
            cooldown_ms=0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            min_trade_usdt=10.0,
            min_position_usdt=5.0,
            max_position_fraction=0.3,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("set_btc_rf"))
async def set_btc_rf_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.update_symbol_profile(
            symbol="BTC/USDT",
            model_type="random_forest",
            buy_threshold=0.6,
            sell_threshold=0.4,
            use_trend_filter=True,
            use_rsi_filter=True,
            target_threshold=0.002,
            cooldown_ms=0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            min_trade_usdt=10.0,
            min_position_usdt=5.0,
            max_position_fraction=0.3,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("set_eth_rf"))
async def set_eth_rf_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.update_symbol_profile(
            symbol="ETH/USDT",
            model_type="random_forest",
            buy_threshold=0.6,
            sell_threshold=0.4,
            use_trend_filter=True,
            use_rsi_filter=True,
            target_threshold=0.002,
            cooldown_ms=0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            min_trade_usdt=10.0,
            min_position_usdt=5.0,
            max_position_fraction=0.3,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("set_sol_rf"))
async def set_sol_rf_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.update_symbol_profile(
            symbol="SOL/USDT",
            model_type="random_forest",
            buy_threshold=0.6,
            sell_threshold=0.4,
            use_trend_filter=True,
            use_rsi_filter=True,
            target_threshold=0.002,
            cooldown_ms=0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            min_trade_usdt=10.0,
            min_position_usdt=5.0,
            max_position_fraction=0.3,
        )
        await message.answer(text)
    finally:
        db.close()


def normalize_symbol_input(raw: str) -> str:
    value = raw.strip().upper()

    if not value:
        raise ValueError("Пустой символ")

    value = value.replace(" ", "")

    if "/" in value:
        return value

    if value.endswith("USDT") and len(value) > 4:
        base = value[:-4]
        return f"{base}/USDT"

    raise ValueError(
        "Неверный формат символа. Используй, например: BTC/USDT или BTCUSDT"
    )


@dp.message(Command("signal"))
async def signal_dynamic_handler(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("Использование: /signal BTC/USDT")
        return

    try:
        symbol = normalize_symbol_input(parts[1])
    except ValueError as exc:
        await message.answer(str(exc))
        return

    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_single_symbol_signal_message(
            symbol=symbol,
            timeframe="5m",
            model_type="auto",
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("profile"))
async def profile_dynamic_handler(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("Использование: /profile BTC/USDT")
        return

    try:
        symbol = normalize_symbol_input(parts[1])
    except ValueError as exc:
        await message.answer(str(exc))
        return

    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_strategy_profile_message(symbol)
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("set_model"))
async def set_model_dynamic_handler(message: Message) -> None:
    parts = (message.text or "").split()

    if len(parts) < 3:
        await message.answer(
            "Использование: /set_model BTC/USDT lstm\n"
            "Доступные модели: lstm, random_forest, logistic_regression, gradient_boosting"
        )
        return

    raw_symbol = parts[1]
    raw_model = parts[2].strip().lower()

    try:
        symbol = normalize_symbol_input(raw_symbol)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    allowed_models = {
        "lstm",
        "random_forest",
        "logistic_regression",
        "gradient_boosting",
    }

    if raw_model not in allowed_models:
        await message.answer(
            "Неизвестная модель.\n"
            "Доступные: lstm, random_forest, logistic_regression, gradient_boosting"
        )
        return

    db = SessionLocal()
    try:
        service = NotificationService(db)

        if raw_model == "lstm":
            text = service.update_symbol_profile(
                symbol=symbol,
                model_type="lstm",
                buy_threshold=0.55,
                sell_threshold=0.2,
                use_trend_filter=False,
                use_rsi_filter=False,
                target_threshold=0.002,
                cooldown_ms=0,
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                min_trade_usdt=10.0,
                min_position_usdt=5.0,
                max_position_fraction=0.3,
            )
        elif raw_model == "random_forest":
            text = service.update_symbol_profile(
                symbol=symbol,
                model_type="random_forest",
                buy_threshold=0.6,
                sell_threshold=0.4,
                use_trend_filter=True,
                use_rsi_filter=True,
                target_threshold=0.002,
                cooldown_ms=0,
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                min_trade_usdt=10.0,
                min_position_usdt=5.0,
                max_position_fraction=0.3,
            )
        elif raw_model == "logistic_regression":
            text = service.update_symbol_profile(
                symbol=symbol,
                model_type="logistic_regression",
                buy_threshold=0.6,
                sell_threshold=0.4,
                use_trend_filter=True,
                use_rsi_filter=True,
                target_threshold=0.002,
                cooldown_ms=0,
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                min_trade_usdt=10.0,
                min_position_usdt=5.0,
                max_position_fraction=0.3,
            )
        else:  # gradient_boosting
            text = service.update_symbol_profile(
                symbol=symbol,
                model_type="gradient_boosting",
                buy_threshold=0.6,
                sell_threshold=0.4,
                use_trend_filter=True,
                use_rsi_filter=True,
                target_threshold=0.002,
                cooldown_ms=0,
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                min_trade_usdt=10.0,
                min_position_usdt=5.0,
                max_position_fraction=0.3,
            )

        await message.answer(text)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
