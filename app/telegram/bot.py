from __future__ import annotations

import asyncio
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.chat_settings_service import ChatSettingsService
from app.services.indicator_service import IndicatorService
from app.services.ingestion_service import IngestionService
from app.services.market_data_service import MarketDataService
from app.services.notification_service import NotificationService
from app.services.subscription_service import SubscriptionService

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# -------------------------
# i18n (RU/EN) - bot layer
# -------------------------
LANG_CALLBACK_PREFIX = "lang:"
LANG_DEFAULT = "ru"
CHAT_LANG: dict[int, str] = {}

I18N: dict[str, dict[str, str]] = {
    "ru": {
        "status_ok": "Бот работает нормально.",
        "pong": "pong",
        "chat_id": "Ваш chat_id: {chat_id}",
        "choose_language": "Выбери язык:",
        "lang_set": "Язык установлен: {lang}",
        "lang_ru": "Русский",
        "lang_en": "English",
        "miniapp_not_configured": (
            "MINIAPP_URL не настроен.\n"
            "Укажи публичный HTTPS URL, например:\n"
            "MINIAPP_URL=https://your-domain.com/miniapp"
        ),
        "miniapp_open": "Открывай Mini App по кнопке ниже (и через меню внизу):",
        "menu_pinned": "Готово. Mini App закреплён в меню (кнопка внизу справа).",
    },
    "en": {
        "status_ok": "Bot is running normally.",
        "pong": "pong",
        "chat_id": "Your chat_id: {chat_id}",
        "choose_language": "Choose language:",
        "lang_set": "Language set: {lang}",
        "lang_ru": "Russian",
        "lang_en": "English",
        "miniapp_not_configured": (
            "MINIAPP_URL is not configured.\n"
            "Set a public HTTPS URL, for example:\n"
            "MINIAPP_URL=https://your-domain.com/miniapp"
        ),
        "miniapp_open": "Open the Mini App using the button below (and via the menu button):",
        "menu_pinned": "Done. Mini App pinned to the chat menu (bottom-right).",
    },
}


def _lang_from_user(message: Message) -> str:
    code = ""
    try:
        code = (message.from_user.language_code or "").lower()
    except Exception:
        code = ""

    if code.startswith("ru"):
        return "ru"
    return "en"


def get_lang(message: Message) -> str:
    """
    Get language for this chat.
    Priority:
    1) In-memory cache (fast)
    2) DB-backed setting (persisted per chat)
    3) Telegram user's language_code (best-effort)
    4) LANG_DEFAULT
    """
    chat_id = int(message.chat.id)

    cached = CHAT_LANG.get(chat_id)
    if cached in {"ru", "en"}:
        return cached

    telegram_code = None
    try:
        telegram_code = message.from_user.language_code if message.from_user else None
    except Exception:
        telegram_code = None

    db = SessionLocal()
    try:
        service = ChatSettingsService(db)
        lang = service.get_language(
            chat_id=chat_id,
            default=LANG_DEFAULT,
            telegram_language_code=telegram_code,
        )
        CHAT_LANG[chat_id] = lang
        return lang
    except Exception:
        # DB unavailable / unexpected error — fall back to Telegram-provided language
        lang = _lang_from_user(message) or LANG_DEFAULT
        CHAT_LANG[chat_id] = lang
        return lang
    finally:
        db.close()


def t(message: Message, key: str, **kwargs: object) -> str:
    lang = get_lang(message)
    template = I18N.get(lang, I18N[LANG_DEFAULT]).get(key, key)
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def get_miniapp_url() -> str:
    return os.getenv("MINIAPP_URL", "").strip()


async def set_miniapp_menu_button(*, chat_id: int) -> bool:
    miniapp_url = get_miniapp_url()
    if not miniapp_url:
        return False

    await bot.set_chat_menu_button(
        chat_id=chat_id,
        menu_button=MenuButtonWebApp(
            text="Mini App",
            web_app=WebAppInfo(url=miniapp_url),
        ),
    )
    return True


def get_help_text() -> str:
    return (
        "AI Crypto Trading Bot\n\n"
        "Команды:\n"
        "/start — старт\n"
        "/help — список команд\n"
        "/status — статус бота\n"
        "/ping — проверка\n"
        "/chatid — показать chat_id\n"
        "/miniapp — открыть Telegram Mini App\n"
        "/menu — закрепить Mini App в меню (кнопка внизу)\n"
        "/available_symbols — доступные торговые пары\n"
        "/find <text> — найти пары, например /find BTC\n"
        "/signals — actionable summary по вашим подпискам или default symbols\n"
        "/scan_all — summary по вашим подпискам или default symbols, включая HOLD\n"
        "/signals_auto — actionable summary через auto profiles\n"
        "/scan_all_auto — summary через auto profiles, включая HOLD\n"
        "/signals_lstm — actionable summary через LSTM\n"
        "/scan_all_lstm — summary через LSTM, включая HOLD\n"
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
        "/portfolio — paper portfolio BTC/USDT\n"
        "/trades — последние сделки BTC/USDT\n"
        "/last_signals — последние сохранённые сигналы по вашим подпискам или default symbols\n"
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


def get_help_text_en() -> str:
    return (
        "AI Crypto Trading Bot\n\n"
        "Commands:\n"
        "/start — start\n"
        "/help — command list\n"
        "/lang — language (RU/EN)\n"
        "/status — status\n"
        "/ping — ping\n"
        "/chatid — show chat_id\n"
        "/miniapp — open Telegram Mini App\n"
        "/menu — pin Mini App to the menu button\n"
        "/available_symbols — available symbols\n"
        "/find <text> — search symbols, e.g. /find BTC\n"
        "/signals — actionable summary for your subscriptions or default symbols\n"
        "/scan_all — summary including HOLD\n"
        "/signal <symbol> — signal for a symbol, e.g. /signal BTC/USDT\n"
        "/profile <symbol> — active strategy profile\n"
        "/set_model <symbol> <model> — change model type\n"
        "/subscribe <symbol> — subscribe\n"
        "/unsubscribe <symbol> — unsubscribe\n"
        "/my_symbols — my subscriptions\n"
        "/portfolio — paper portfolio\n"
        "/trades — recent trades\n"
    )


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

    return f"{value}/USDT"


def get_chat_symbols(db, chat_id: int) -> list[str]:
    sub_service = SubscriptionService(db)
    symbols = sub_service.get_symbols_for_chat(chat_id)
    return symbols if symbols else settings.get_default_symbols()


def _format_signal_error(symbol: str, exc: Exception) -> str:
    msg = str(exc)

    if "Dataset is empty" in msg or "No data available" in msg:
        return (
            f"Недостаточно данных для {symbol}.\n\n"
            "Я запущу догрузку свечей и индикаторов для этой пары. "
            "Попробуй снова через 1–2 минуты.\n\n"
            f"Если ты ещё не подписан(а), подпишись: /subscribe {symbol}"
        )

    return f"Ошибка при расчёте сигнала для {symbol}:\n{msg}"


def _trigger_symbol_warmup(
    symbol: str, timeframe: str = "5m", limit: int = 300
) -> None:
    """
    Best-effort warmup:
    - pull recent candles for (symbol, timeframe)
    - calculate and save indicators
    Runs in a background thread to avoid blocking the bot event loop.
    """

    async def _runner() -> None:
        def _sync() -> None:
            db = SessionLocal()
            try:
                IngestionService(db).update_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit,
                )
                IndicatorService(db).calculate_and_save(
                    symbol=symbol,
                    timeframe=timeframe,
                )
            except Exception as exc:
                print(f"[warmup] failed for {symbol} {timeframe}: {exc}")
            finally:
                db.close()

        await asyncio.to_thread(_sync)

    asyncio.create_task(_runner())


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    lang = get_lang(message)
    if lang == "en":
        await message.answer(get_help_text_en())
    else:
        await message.answer(get_help_text())

    # Best-effort: set bottom-right menu button to open the Mini App
    try:
        await set_miniapp_menu_button(chat_id=message.chat.id)
    except Exception:
        # Don't block /start if Telegram API call fails
        pass


@dp.message(Command("help"))
async def help_handler(message: Message) -> None:
    lang = get_lang(message)
    if lang == "en":
        await message.answer(get_help_text_en())
    else:
        await message.answer(get_help_text())


@dp.message(Command("status"))
async def status_handler(message: Message) -> None:
    await message.answer(t(message, "status_ok"))


@dp.message(Command("ping"))
async def ping_handler(message: Message) -> None:
    await message.answer(t(message, "pong"))


@dp.message(Command("chatid"))
async def chatid_handler(message: Message) -> None:
    await message.answer(t(message, "chat_id", chat_id=message.chat.id))


@dp.message(Command("lang"))
async def lang_handler(message: Message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🇷🇺 {I18N['ru']['lang_ru']}",
                    callback_data=f"{LANG_CALLBACK_PREFIX}ru",
                ),
                InlineKeyboardButton(
                    text=f"🇬🇧 {I18N['en']['lang_en']}",
                    callback_data=f"{LANG_CALLBACK_PREFIX}en",
                ),
            ]
        ]
    )
    await message.answer(t(message, "choose_language"), reply_markup=kb)


@dp.callback_query(F.data.startswith(LANG_CALLBACK_PREFIX))
async def lang_callback_handler(callback: CallbackQuery) -> None:
    data = callback.data or ""
    lang = data[len(LANG_CALLBACK_PREFIX) :].strip().lower()
    if lang not in {"ru", "en"}:
        await callback.answer("Bad language", show_alert=False)
        return

    if callback.message:
        chat_id = int(callback.message.chat.id)

        # Persist language per chat (DB-backed)
        db = SessionLocal()
        try:
            ChatSettingsService(db).set_language(chat_id=chat_id, language=lang)
        finally:
            db.close()

        # Update cache
        CHAT_LANG[chat_id] = lang

        label = I18N[lang]["lang_ru"] if lang == "ru" else I18N[lang]["lang_en"]
        await callback.message.answer(I18N[lang]["lang_set"].format(lang=label))

    await callback.answer()


@dp.message(Command("miniapp"))
async def miniapp_handler(message: Message) -> None:
    miniapp_url = get_miniapp_url()

    if not miniapp_url:
        await message.answer(t(message, "miniapp_not_configured"))
        return

    # Also pin Mini App into the chat menu button (bottom-right)
    try:
        await set_miniapp_menu_button(chat_id=message.chat.id)
    except Exception:
        pass

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть Mini App",
                    web_app=WebAppInfo(url=miniapp_url),
                )
            ]
        ]
    )

    await message.answer(
        t(message, "miniapp_open"),
        reply_markup=kb,
    )


@dp.message(Command("menu"))
async def menu_handler(message: Message) -> None:
    miniapp_url = get_miniapp_url()

    if not miniapp_url:
        await message.answer(t(message, "miniapp_not_configured"))
        return

    await set_miniapp_menu_button(chat_id=message.chat.id)
    await message.answer(t(message, "menu_pinned"))


@dp.message(Command("signals"))
async def signals_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        symbols = get_chat_symbols(db, message.chat.id)
        service = NotificationService(db)

        _, text = service.format_multi_symbol_signals_summary(
            symbols=symbols,
            timeframe="5m",
            model_type="logistic_regression",
            actionable_only=True,
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("scan_all"))
async def scan_all_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        symbols = get_chat_symbols(db, message.chat.id)
        service = NotificationService(db)

        _, text = service.format_multi_symbol_signals_summary(
            symbols=symbols,
            timeframe="5m",
            model_type="logistic_regression",
            actionable_only=False,
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signals_lstm"))
async def signals_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        symbols = get_chat_symbols(db, message.chat.id)
        service = NotificationService(db)

        _, text = service.format_multi_symbol_signals_summary(
            symbols=symbols,
            timeframe="5m",
            model_type="lstm",
            actionable_only=True,
            use_trend_filter=False,
            use_rsi_filter=False,
            buy_threshold=0.55,
            sell_threshold=0.2,
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("scan_all_lstm"))
async def scan_all_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        symbols = get_chat_symbols(db, message.chat.id)
        service = NotificationService(db)

        _, text = service.format_multi_symbol_signals_summary(
            symbols=symbols,
            timeframe="5m",
            model_type="lstm",
            actionable_only=False,
            use_trend_filter=False,
            use_rsi_filter=False,
            buy_threshold=0.55,
            sell_threshold=0.2,
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("signals_auto"))
async def signals_auto_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        symbols = get_chat_symbols(db, message.chat.id)
        service = NotificationService(db)

        _, text = service.format_multi_symbol_signals_summary(
            symbols=symbols,
            timeframe="5m",
            model_type="auto",
            actionable_only=True,
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("scan_all_auto"))
async def scan_all_auto_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        symbols = get_chat_symbols(db, message.chat.id)
        service = NotificationService(db)

        _, text = service.format_multi_symbol_signals_summary(
            symbols=symbols,
            timeframe="5m",
            model_type="auto",
            actionable_only=False,
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("portfolio"))
async def portfolio_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_portfolio_message(
            symbol="BTC/USDT",
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("trades"))
async def trades_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_recent_trades_message(
            symbol="BTC/USDT",
            limit=5,
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("last_signals"))
async def last_signals_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        symbols = get_chat_symbols(db, message.chat.id)
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

        # Warm up market data & indicators so /signal works even for new subscriptions
        _trigger_symbol_warmup("BTC/USDT", timeframe="5m")
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

        # Warm up market data & indicators so /signal works even if there was no data yet
        _trigger_symbol_warmup(symbol, timeframe="5m")
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


AVAILABLE_SYMBOLS_PAGE_SIZE = 30
AVAILABLE_SYMBOLS_MAX_LIMIT = 5000
AVAILABLE_SYMBOLS_CALLBACK_PREFIX = "availsym:"


def _build_available_symbols_page(
    *,
    page: int,
    quote: str = "USDT",
    only_active: bool = True,
    spot_only: bool = True,
) -> tuple[str, InlineKeyboardMarkup]:
    safe_page = max(1, int(page))

    market_service = MarketDataService()
    all_symbols = market_service.get_available_symbols(
        quote=quote,
        only_active=only_active,
        spot_only=spot_only,
        limit=AVAILABLE_SYMBOLS_MAX_LIMIT,
    )

    total = len(all_symbols)
    page_size = AVAILABLE_SYMBOLS_PAGE_SIZE
    total_pages = max(1, (total + page_size - 1) // page_size)

    if safe_page > total_pages:
        safe_page = total_pages

    start = (safe_page - 1) * page_size
    end = start + page_size
    symbols = all_symbols[start:end]

    header = (
        f"📚 Available symbols ({quote})\n"
        f"Page {safe_page}/{total_pages}\n"
        f"Total: {total}\n"
    )

    body = "\n".join(f"- {s}" for s in symbols) if symbols else "(no symbols)"
    text = f"{header}\n{body}"

    prev_page = safe_page - 1
    next_page = safe_page + 1

    buttons: list[list[InlineKeyboardButton]] = []

    nav_row: list[InlineKeyboardButton] = []
    if safe_page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Prev",
                callback_data=f"{AVAILABLE_SYMBOLS_CALLBACK_PREFIX}{prev_page}",
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text="🔄 Refresh",
            callback_data=f"{AVAILABLE_SYMBOLS_CALLBACK_PREFIX}{safe_page}",
        )
    )
    if safe_page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Next ➡️",
                callback_data=f"{AVAILABLE_SYMBOLS_CALLBACK_PREFIX}{next_page}",
            )
        )
    buttons.append(nav_row)

    buttons.append(
        [
            InlineKeyboardButton(
                text="❌ Close",
                callback_data=f"{AVAILABLE_SYMBOLS_CALLBACK_PREFIX}close",
            )
        ]
    )

    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("available_symbols"))
async def available_symbols_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        # DB is not required for symbol listing, but kept for consistency with other handlers.
        text, kb = _build_available_symbols_page(page=1, quote="USDT")
        await message.answer(text, reply_markup=kb)
    finally:
        db.close()


@dp.callback_query(F.data.startswith(AVAILABLE_SYMBOLS_CALLBACK_PREFIX))
async def available_symbols_pagination_handler(callback: CallbackQuery) -> None:
    data = callback.data or ""
    payload = data[len(AVAILABLE_SYMBOLS_CALLBACK_PREFIX) :].strip()

    if payload == "close":
        try:
            if callback.message:
                await callback.message.delete()
        finally:
            await callback.answer()
        return

    try:
        page = int(payload)
    except Exception:
        await callback.answer("Bad page", show_alert=False)
        return

    try:
        text, kb = _build_available_symbols_page(page=page, quote="USDT")
        if callback.message:
            await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except Exception as exc:
        await callback.answer("Failed", show_alert=False)
        if callback.message:
            await callback.message.answer(f"Ошибка пагинации: {exc}")


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


@dp.message(Command("profile_btc"))
async def profile_btc_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_strategy_profile_message(
            "BTC/USDT",
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("profile_eth"))
async def profile_eth_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_strategy_profile_message(
            "ETH/USDT",
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("profile_sol"))
async def profile_sol_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.format_strategy_profile_message(
            "SOL/USDT",
            chat_id=message.chat.id,
        )
        await message.answer(text)
    finally:
        db.close()


@dp.message(Command("set_btc_lstm"))
async def set_btc_lstm_handler(message: Message) -> None:
    db = SessionLocal()
    try:
        service = NotificationService(db)
        text = service.update_symbol_profile(
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
            chat_id=message.chat.id,
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
        try:
            text = service.format_single_symbol_signal_message(
                symbol=symbol,
                timeframe="5m",
                model_type="auto",
                chat_id=message.chat.id,
            )
        except Exception as exc:
            # If there's no dataset yet for this symbol, warm it up automatically.
            if "Dataset is empty" in str(exc) or "No data available" in str(exc):
                _trigger_symbol_warmup(symbol, timeframe="5m")
            await message.answer(_format_signal_error(symbol, exc))
            return

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
        text = service.format_strategy_profile_message(
            symbol,
            chat_id=message.chat.id,
        )
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
                chat_id=message.chat.id,
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
                chat_id=message.chat.id,
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
                chat_id=message.chat.id,
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
        else:
            text = service.update_symbol_profile(
                chat_id=message.chat.id,
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


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
