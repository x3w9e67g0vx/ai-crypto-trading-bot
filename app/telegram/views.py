"""Bot screens: each function returns the text and keyboard of one message."""

from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy.orm import Session

from app.game.chat_leagues import chat_league_table
from app.game.config import SeasonKind
from app.game.leaderboard import standings
from app.game.leagues import group_portfolio_ids
from app.game.models import ChatLeague, Player
from app.game.quotes import QuoteBook
from app.game.referrals import ref_link
from app.game.seasons import current_portfolio
from app.i18n.strings import t

NOTIFY_FLAGS = ("notify_overtaken", "notify_ai_open", "notify_season_end")
LEAGUE_TABLE_ROWS = 30

Screen = tuple[str, InlineKeyboardMarkup | None]


def play_keyboard(lang: str, miniapp_url: str) -> InlineKeyboardMarkup | None:
    if not miniapp_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn.play", lang=lang), web_app=WebAppInfo(url=miniapp_url))]]
    )


def start_view(player: Player, miniapp_url: str) -> Screen:
    lang = player.language
    text = t("start.welcome", lang=lang, nickname=escape(player.nickname), disclaimer=t("disclaimer", lang=lang))
    return text, play_keyboard(lang, miniapp_url)


def play_view(player: Player, miniapp_url: str) -> Screen:
    lang = player.language
    if not miniapp_url:
        return t("play.no_url", lang=lang), None
    return t("play.open", lang=lang), play_keyboard(lang, miniapp_url)


def rank_view(db: Session, player: Player, quotes: QuoteBook, now_ms: int, bot_username: str) -> str:
    """Places in the sprint (global) and the week (league group), best AI, invite link."""
    lang = player.language
    lines = [t("rank.title", lang=lang, tier=t(f"tier.{player.league_tier}", lang=lang))]
    best_ai = None
    for kind in (SeasonKind.SPRINT, SeasonKind.WEEK):
        portfolio = current_portfolio(db, player, kind, now_ms)
        _, portfolio_ids = group_portfolio_ids(db, portfolio)
        table = standings(db, portfolio.season, quotes, now_ms, portfolio_ids=portfolio_ids)
        mine = next(row for row in table if row.portfolio_id == portfolio.id)
        ranked = sum(1 for row in table if row.rank is not None)
        place = (
            t("rank.place", lang=lang, rank=mine.rank, total=ranked)
            if mine.rank is not None
            else t("rank.unranked", lang=lang)
        )
        lines.append(
            t("rank.line", lang=lang, season=t(f"season.{kind.value}", lang=lang), place=place,
              ret=mine.return_pct, trades=mine.trades)
        )
        if kind == SeasonKind.WEEK:
            best_ai = max((row for row in table if row.is_ai), key=lambda row: row.return_pct, default=None)
    if best_ai is not None:
        lines.append(t("rank.best_ai", lang=lang, nickname=escape(best_ai.nickname), ret=best_ai.return_pct))
    lines += ["", t("rank.ref", lang=lang, link=ref_link(bot_username, player))]
    return "\n".join(lines)


def settings_view(player: Player) -> Screen:
    lang = player.language
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if getattr(player, flag) else '❌'} {t(f'settings.{flag}', lang=lang)}",
                callback_data=f"set:{flag}",
            )
        ]
        for flag in NOTIFY_FLAGS
    ]
    rows.append([InlineKeyboardButton(text=t("settings.lang", lang=lang), callback_data="set:lang")])
    return t("settings.title", lang=lang), InlineKeyboardMarkup(inline_keyboard=rows)


def help_view(lang: str) -> str:
    return t("help.text", lang=lang, disclaimer=t("disclaimer", lang=lang))


def league_view(db: Session, league: ChatLeague, quotes: QuoteBook, now_ms: int, lang: str) -> Screen:
    table = chat_league_table(db, league, quotes, now_ms)
    lines = [t("league.title", lang=lang, title=escape(league.title)), ""]
    humans = [row for row in table if not row.is_ai]
    if not humans:
        lines.append(t("league.empty", lang=lang))
    for place, row in enumerate(table[:LEAGUE_TABLE_ROWS], start=1):
        nickname = escape(row.nickname) + (f" {t('league.ai', lang=lang)}" if row.is_ai else "")
        lines.append(t("league.row", lang=lang, place=place, nickname=nickname, ret=row.return_pct, trades=row.trades))
    lines += ["", t("disclaimer", lang=lang)]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("league.btn_join", lang=lang), callback_data=f"league:join:{league.id}"),
                InlineKeyboardButton(text=t("league.btn_refresh", lang=lang), callback_data=f"league:refresh:{league.id}"),
            ]
        ]
    )
    return "\n".join(lines), keyboard
