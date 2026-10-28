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
        "disclaimer": (
            "🎓 Образовательная игра 18+. Не инвестиционная рекомендация, "
            "деньги виртуальные, цены — Binance."
        ),
        "banned": "Аккаунт заблокирован.",
        "btn.play": "🎮 Играть",
        "start.welcome": (
            "Привет, <b>{nickname}</b>! Это VEYDRANOX — трейдинг против ИИ.\n\n"
            "На каждый сезон — виртуальные $10 000: Спринт (24 ч) и Неделя с лигами. "
            "Торгуй по реальным ценам и попробуй обойти ИИ-персонажей.\n\n{disclaimer}"
        ),
        "play.open": "Открывай игру по кнопке:",
        "play.no_url": "Mini App ещё не подключён — попробуй позже.",
        "season.sprint": "Спринт",
        "season.week": "Неделя",
        "tier.bronze": "Бронза",
        "tier.silver": "Серебро",
        "tier.gold": "Золото",
        "tier.platinum": "Платина",
        "tier.diamond": "Алмаз",
        "rank.title": "🏆 <b>Твои сезоны</b> · лига: {tier}",
        "rank.line": "{season}: {place} · {ret:+.2f}% · сделок: {trades}",
        "rank.place": "#{rank} из {total}",
        "rank.unranked": "без места (нужно ≥ 5 сделок)",
        "rank.best_ai": "🤖 Лучший ИИ недели: {nickname} {ret:+.2f}%",
        "rank.ref": "Позови друга: {link}",
        "learn.title": "📚 <b>Уроки</b>\nУровень {level} · {xp} XP{next}",
        "learn.next": " · до следующего уровня {need} XP",
        "learn.footer": "За каждый урок — {xp} XP, за каждую закрытую сделку — {trade_xp} XP. Новые уровни открывают новые пары.",
        "btn.lessons": "📚 Открыть уроки",
        "settings.title": "⚙️ <b>Настройки</b>\nУведомления (не больше 3 в день):",
        "settings.notify_overtaken": "Меня обогнали в лиге",
        "settings.notify_ai_open": "ИИ открыл позицию (Pro)",
        "settings.notify_season_end": "Сезон кончается через час",
        "settings.lang": "🌐 Language: English",
        "help.text": (
            "<b>VEYDRANOX</b> — учебная игра в трейдинг против ИИ.\n\n"
            "/play — открыть игру\n"
            "/rank — места в сезонах и реф-ссылка\n"
            "/learn — уроки\n"
            "/settings — уведомления и язык\n"
            "/help — эта справка\n"
            "/league — частная лига (в группе)\n\n{disclaimer}"
        ),
        "league.private": "Частные лиги живут в группах: добавь бота в чат и напиши там /league.",
        "league.title": "🏁 <b>Лига чата «{title}»</b> — недельный сезон",
        "league.empty": "Пока никого. Жми «Вступить»!",
        "league.row": "{place}. {nickname} {ret:+.2f}% · {trades}",
        "league.ai": "🤖",
        "league.btn_join": "✋ Вступить",
        "league.btn_refresh": "🔄 Обновить",
        "league.joined": "Ты в лиге! Торгуй в недельном сезоне: /play в личке с ботом.",
        "league.already": "Ты уже в этой лиге.",
        "side.long": "лонг",
        "side.short": "шорт",
        "notify.overtaken": "📉 Тебя обогнали: теперь ты #{new_rank} в недельной группе (было #{old_rank}).",
        "notify.ai_open": "🤖 {nickname} открыл {side} по {symbol}.",
        "notify.season_end": "⏳ {season} закончится через час — открытые позиции закроются по рынку.",
        "notify.footer": "Отключить: /settings",
        "admin.stats": (
            "<b>Админка</b>\nИгроков: {players} (+{new_24h} за 24 ч)\n"
            "D1: {d1_kept}/{d1_total} · D7: {d7_kept}/{d7_total}\n"
            "Активных в неделе: {week_active}\nСделок сегодня: {trades_today}"
        ),
        "admin.usage": "/admin · /admin ban|unban &lt;ник&gt; · /admin end|restart sprint|week",
        "admin.banned": "{nickname} заблокирован.",
        "admin.unbanned": "{nickname} разблокирован.",
        "admin.not_found": "Игрок {nickname} не найден.",
        "admin.ended": "Сезон #{old_id} ({kind}) завершён{pending}. Новый сезон #{new_id} открыт.",
        "admin.pending": " — позиции закроются по первой свежей цене",
        "card.tagline": "трейдинг против ИИ",
        "card.season.week": "за неделю",
        "card.season.sprint": "за спринт",
        "card.rank": "#{rank} в рейтинге",
        "card.unranked": "без места: нужно 5 сделок",
        "card.beat_ai": "ИИ позади на {margin:.1f}%",
        "card.behind_ai": "Попробуй обойти ИИ",
        "card.footer": "Образовательная игра 18+ · деньги виртуальные · цены Binance",
    },
    "en": {
        "disclaimer": (
            "🎓 Educational game, 18+. Not investment advice, "
            "the money is virtual, prices are from Binance."
        ),
        "banned": "Your account is banned.",
        "btn.play": "🎮 Play",
        "start.welcome": (
            "Hi, <b>{nickname}</b>! This is VEYDRANOX — trading against AI.\n\n"
            "Every season gives you virtual $10,000: the Sprint (24 h) and the Week with leagues. "
            "Trade at real prices and try to beat the AI personas.\n\n{disclaimer}"
        ),
        "play.open": "Open the game with the button:",
        "play.no_url": "The Mini App is not connected yet — try again later.",
        "season.sprint": "Sprint",
        "season.week": "Week",
        "tier.bronze": "Bronze",
        "tier.silver": "Silver",
        "tier.gold": "Gold",
        "tier.platinum": "Platinum",
        "tier.diamond": "Diamond",
        "rank.title": "🏆 <b>Your seasons</b> · league: {tier}",
        "rank.line": "{season}: {place} · {ret:+.2f}% · trades: {trades}",
        "rank.place": "#{rank} of {total}",
        "rank.unranked": "unranked (needs ≥ 5 trades)",
        "rank.best_ai": "🤖 Best AI this week: {nickname} {ret:+.2f}%",
        "rank.ref": "Invite a friend: {link}",
        "learn.title": "📚 <b>Lessons</b>\nLevel {level} · {xp} XP{next}",
        "learn.next": " · {need} XP to the next level",
        "learn.footer": "Each lesson gives {xp} XP, each closed trade {trade_xp} XP. New levels unlock new pairs.",
        "btn.lessons": "📚 Open lessons",
        "settings.title": "⚙️ <b>Settings</b>\nNotifications (at most 3 a day):",
        "settings.notify_overtaken": "Someone overtook me",
        "settings.notify_ai_open": "AI opened a position (Pro)",
        "settings.notify_season_end": "Season ends in an hour",
        "settings.lang": "🌐 Язык: русский",
        "help.text": (
            "<b>VEYDRANOX</b> — an educational trading game against AI.\n\n"
            "/play — open the game\n"
            "/rank — season places and invite link\n"
            "/learn — lessons\n"
            "/settings — notifications and language\n"
            "/help — this help\n"
            "/league — private league (in a group)\n\n{disclaimer}"
        ),
        "league.private": "Private leagues live in groups: add the bot to a chat and send /league there.",
        "league.title": "🏁 <b>«{title}» chat league</b> — week season",
        "league.empty": "Nobody yet. Tap «Join»!",
        "league.row": "{place}. {nickname} {ret:+.2f}% · {trades}",
        "league.ai": "🤖",
        "league.btn_join": "✋ Join",
        "league.btn_refresh": "🔄 Refresh",
        "league.joined": "You're in! Trade in the week season: /play in a private chat with the bot.",
        "league.already": "You're already in this league.",
        "side.long": "a long",
        "side.short": "a short",
        "notify.overtaken": "📉 You were overtaken: now #{new_rank} in your week group (was #{old_rank}).",
        "notify.ai_open": "🤖 {nickname} opened {side} on {symbol}.",
        "notify.season_end": "⏳ The {season} ends in an hour — open positions will be closed at market.",
        "notify.footer": "Turn off: /settings",
        "admin.stats": (
            "<b>Admin</b>\nPlayers: {players} (+{new_24h} in 24 h)\n"
            "D1: {d1_kept}/{d1_total} · D7: {d7_kept}/{d7_total}\n"
            "Active this week: {week_active}\nTrades today: {trades_today}"
        ),
        "admin.usage": "/admin · /admin ban|unban &lt;nick&gt; · /admin end|restart sprint|week",
        "admin.banned": "{nickname} is banned.",
        "admin.unbanned": "{nickname} is unbanned.",
        "admin.not_found": "Player {nickname} not found.",
        "admin.ended": "Season #{old_id} ({kind}) ended{pending}. New season #{new_id} is open.",
        "admin.pending": " — positions close at the first fresh price",
        "card.tagline": "trading against AI",
        "card.season.week": "this week",
        "card.season.sprint": "this sprint",
        "card.rank": "#{rank} in the ranking",
        "card.unranked": "no place yet: 5 trades needed",
        "card.beat_ai": "AI left behind by {margin:.1f}%",
        "card.behind_ai": "Try to beat the AI",
        "card.footer": "Educational game 18+ · virtual money · Binance prices",
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
      t("banned", lang="ru")
      t("rank.place", lang="en", rank=1, total=10)

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
