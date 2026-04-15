from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class I18nConfig:
    default_lang: str = "ru"
    fallback_lang: str = "en"


SUPPORTED_LANGS: set[str] = {"ru", "en"}

# -----------------------------------------------------------------------------
# Translation keys:
# - Keep keys stable; change values freely.
# - Use Python format placeholders: "{symbol}", "{timeframe}", etc.
# -----------------------------------------------------------------------------
STRINGS: dict[str, dict[str, str]] = {
    "ru": {
        # Generic
        "common.ok": "Ок",
        "common.error": "Ошибка",
        "common.close": "Закрыть",
        "common.refresh": "Обновить",
        "common.prev": "Назад",
        "common.next": "Вперёд",
        # Bot meta
        "bot.welcome_title": "AI Crypto Trading Bot",
        "bot.status_ok": "Бот работает нормально.",
        "bot.ping_pong": "pong",
        "bot.your_chat_id": "Ваш chat_id: {chat_id}",
        # Mini app
        "bot.miniapp_missing_url": (
            "MINIAPP_URL не настроен.\n"
            "Укажи публичный HTTPS URL, например:\n"
            "MINIAPP_URL=https://your-domain.com/miniapp"
        ),
        "bot.miniapp_open": "Открывай Mini App по кнопке ниже (и через меню внизу):",
        "bot.menu_pinned": "Готово. Mini App закреплён в меню (кнопка внизу справа).",
        # Subscriptions
        "subs.none": "У вас пока нет подписок.",
        "subs.list_title": "Ваши подписки:\n{symbols}",
        "subs.subscribe_usage": (
            "Укажи символ. Пример:\n"
            "/subscribe BTC\n"
            "/subscribe ETH\n"
            "/subscribe AAVE/USDT"
        ),
        "subs.unsubscribe_usage": (
            "Укажи символ. Пример:\n"
            "/unsubscribe BTC/USDT\n"
            "/unsubscribe ETH\n"
            "/unsubscribe SOL"
        ),
        "subs.symbol_not_supported": (
            "Символ не поддерживается или не найден: {symbol}\n\n"
            "Примеры доступных символов:\n{preview}"
        ),
        # Signals / data readiness
        "signals.dataset_empty": (
            "Недостаточно данных для {symbol}.\n\n"
            "Я запущу догрузку свечей и индикаторов для этой пары. "
            "Попробуй снова через 1–2 минуты.\n\n"
            "Если ты ещё не подписан(а), подпишись: /subscribe {symbol}"
        ),
        "signals.error_generic": "Ошибка при расчёте сигнала для {symbol}:\n{error}",
        # Find
        "find.usage": "Укажи текст для поиска. Пример:\n/find BTC\n/find AAVE\n/find DOGE",
        # Available symbols
        "markets.available_title": "📚 Доступные символы ({quote})\nСтраница {page}/{pages}\nВсего: {total}\n",
    },
    "en": {
        # Generic
        "common.ok": "Ok",
        "common.error": "Error",
        "common.close": "Close",
        "common.refresh": "Refresh",
        "common.prev": "Prev",
        "common.next": "Next",
        # Bot meta
        "bot.welcome_title": "AI Crypto Trading Bot",
        "bot.status_ok": "Bot is running нормально.",
        "bot.ping_pong": "pong",
        "bot.your_chat_id": "Your chat_id: {chat_id}",
        # Mini app
        "bot.miniapp_missing_url": (
            "MINIAPP_URL is not configured.\n"
            "Set a public HTTPS URL, for example:\n"
            "MINIAPP_URL=https://your-domain.com/miniapp"
        ),
        "bot.miniapp_open": "Open the Mini App using the button below (and via the bottom menu):",
        "bot.menu_pinned": "Done. Mini App is pinned in the chat menu (bottom-right button).",
        # Subscriptions
        "subs.none": "You have no subscriptions yet.",
        "subs.list_title": "Your subscriptions:\n{symbols}",
        "subs.subscribe_usage": (
            "Provide a symbol. Examples:\n"
            "/subscribe BTC\n"
            "/subscribe ETH\n"
            "/subscribe AAVE/USDT"
        ),
        "subs.unsubscribe_usage": (
            "Provide a symbol. Examples:\n"
            "/unsubscribe BTC/USDT\n"
            "/unsubscribe ETH\n"
            "/unsubscribe SOL"
        ),
        "subs.symbol_not_supported": (
            "Symbol is not supported or not found: {symbol}\n\n"
            "Some available symbols:\n{preview}"
        ),
        # Signals / data readiness
        "signals.dataset_empty": (
            "Not enough data for {symbol}.\n\n"
            "I will fetch candles and compute indicators for this pair. "
            "Try again in 1–2 minutes.\n\n"
            "If you're not subscribed yet: /subscribe {symbol}"
        ),
        "signals.error_generic": "Failed to compute signal for {symbol}:\n{error}",
        # Find
        "find.usage": "Provide search text. Examples:\n/find BTC\n/find AAVE\n/find DOGE",
        # Available symbols
        "markets.available_title": "📚 Available symbols ({quote})\nPage {page}/{pages}\nTotal: {total}\n",
    },
}


def normalize_lang(lang: str | None, config: I18nConfig | None = None) -> str:
    """
    Normalize language to a supported code ('ru' / 'en').

    Accepts:
    - 'ru', 'en'
    - 'ru-RU', 'en-US' (will map to base language)
    """
    cfg = config or I18nConfig()
    raw = (lang or "").strip().lower()
    if not raw:
        return cfg.default_lang

    base = raw.split("-")[0].split("_")[0]
    if base in SUPPORTED_LANGS:
        return base

    return cfg.default_lang


def t(
    key: str,
    *,
    lang: str | None = None,
    config: I18nConfig | None = None,
    params: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    """
    Translation helper.

    Usage:
      t("bot.status_ok", lang="ru")
      t("bot.your_chat_id", lang="en", chat_id=123)

    Fallback order:
      1) requested lang
      2) config.fallback_lang
      3) key itself (so missing keys are visible)
    """
    cfg = config or I18nConfig()
    resolved_lang = normalize_lang(lang, cfg)

    fmt_params: dict[str, Any] = {}
    if params:
        fmt_params.update(dict(params))
    fmt_params.update(kwargs)

    # resolve string
    lang_table = STRINGS.get(resolved_lang, {})
    template = lang_table.get(key)

    if template is None:
        template = STRINGS.get(cfg.fallback_lang, {}).get(key)

    if template is None:
        # Make missing keys obvious in UI
        template = key

    try:
        return template.format(**fmt_params)
    except Exception:
        # If formatting fails due to missing params, return template as-is
        return template
