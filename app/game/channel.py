"""Template posts for the public channel (Russian only, spec 4.7): no LLM, real game data."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape

from sqlalchemy.orm import Session

from app.core.db.models import Candle
from app.game.config import (
    AI_SYMBOLS,
    AI_VISIBILITY_DELAY_MS,
    CHART_TIMEFRAME,
    DAY_MS,
    HOUR_MS,
    XP_PER_LESSON,
    SeasonKind,
)
from app.game.charts import candle_chart
from app.game.insights import CANDLE_MS, indicators_at, trade_review
from app.game.leaderboard import standings
from app.game.lessons import get_lesson, get_lessons
from app.game.models import AiDecision, Badge, Fill, Player, Portfolio, Position, Season
from app.game.quotes import QuoteBook
from app.i18n.strings import t

LANG = "ru"
CHART_CANDLES = 100
AI_MOVE_MAX_CANDLES = 300
LESSON_CHART_SYMBOL = "BTC/USDT"
RSI_LESSON = "07"
TOP_DAY = 3
TOP_SEASON = 5
CHANNEL_BADGES = ("sniper", "iron_nerves")


@dataclass(frozen=True)
class Post:
    kind: str  # morning | lesson | evening | season | ai_move
    key: str
    text: str
    image: bytes | None = None


def _(key: str, **params) -> str:
    return t(key, lang=LANG, **params)


def day_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


def _post(kind: str, key: str, lines: list[str], bot_username: str, image: bytes | None = None) -> Post:
    footer = _("channel.footer", disclaimer=_("disclaimer"), link=f"https://t.me/{bot_username}")
    return Post(kind, key, "\n".join(lines) + "\n\n" + footer, image)


def _price(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _markdown(text: str) -> str:
    """Lesson text to Telegram HTML: escaped, **bold** kept."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))


def _candles(db: Session, symbol: str, until_ms: int, *, since_ms: int | None = None, limit: int = CHART_CANDLES) -> list[Candle]:
    """Candles closed by until_ms, oldest first."""
    query = db.query(Candle).filter(
        Candle.symbol == symbol,
        Candle.timeframe == CHART_TIMEFRAME,
        Candle.timestamp <= until_ms - CANDLE_MS,
    )
    if since_ms is not None:
        query = query.filter(Candle.timestamp >= since_ms)
    return list(reversed(query.order_by(Candle.timestamp.desc()).limit(limit).all()))


def _banned_ids(db: Session) -> set[int]:
    return {player_id for (player_id,) in db.query(Player.id).filter(Player.is_banned.is_(True))}


def _public_opinions(db: Session, symbol: str, now_ms: int) -> list[str]:
    """Each AI's latest opinion with the free players' delay: the channel never shows what Pro sees first."""
    visible_until = now_ms - AI_VISIBILITY_DELAY_MS
    lines = []
    for ai in db.query(Player).filter_by(is_ai=True).order_by(Player.id):
        decision = (
            db.query(AiDecision)
            .filter(
                AiDecision.player_id == ai.id,
                AiDecision.symbol == symbol,
                AiDecision.created_at <= visible_until,
                AiDecision.created_at > visible_until - HOUR_MS,
            )
            .order_by(AiDecision.created_at.desc(), AiDecision.id.desc())
            .first()
        )
        if decision is not None:
            lines.append(_("channel.morning.ai", nickname=escape(ai.nickname),
                           view=_(f"channel.view.{decision.view}"), prob=decision.probability_up * 100))
    return lines


def morning_post(db: Session, now_ms: int, bot_username: str) -> Post | None:
    """BTC/ETH/SOL: price, 24h change, indicators and every AI's opinion."""
    blocks = []
    for symbol in AI_SYMBOLS:
        indicators = indicators_at(db, symbol, now_ms)
        if indicators is None:
            continue
        last = _candles(db, symbol, now_ms, limit=1)[0]
        day_ago = _candles(db, symbol, now_ms - DAY_MS, limit=1)
        change = _("channel.morning.change", pct=(last.close / day_ago[0].close - 1) * 100) if day_ago else ""
        rsi = f"{indicators.rsi:.0f}" if indicators.rsi is not None else "—"
        lines = [_("channel.morning.pair", symbol=symbol, price=_price(last.close), change=change, rsi=rsi,
                   trend=_(f"channel.trend.{indicators.trend}"))]
        blocks.append("\n".join(lines + _public_opinions(db, symbol, now_ms)))
    if not blocks:
        return None
    return _post("morning", day_key(now_ms),
                 [_("channel.morning.title"), "", "\n\n".join(blocks), "", _("channel.morning.outro")], bot_username)


def lesson_post(db: Session, now_ms: int, bot_username: str) -> Post:
    """Lesson of the day: the RSI lesson when BTC is overbought or oversold, otherwise the next one in turn."""
    indicators = indicators_at(db, LESSON_CHART_SYMBOL, now_ms)
    rsi = indicators.rsi if indicators is not None else None
    lines = []
    if rsi is not None and (rsi > 70 or rsi < 30):
        lesson = get_lesson(LANG, RSI_LESSON)
        lines.append(_("channel.lesson.title", title=escape(lesson.title)))
        lines.append(_("channel.lesson.rsi", rsi=rsi))
    else:
        lessons = get_lessons(LANG)
        lesson = lessons[(now_ms // DAY_MS) % len(lessons)]
        lines.append(_("channel.lesson.title", title=escape(lesson.title)))
    paragraph = next((block["text"] for block in lesson.blocks if block["type"] == "p"), None)
    if paragraph:
        lines += ["", _markdown(paragraph)]
    lines += ["", _("channel.lesson.question", question=escape(lesson.question))]
    lines += [f"• {escape(option)}" for option in lesson.options]
    lines += ["", _("channel.lesson.cta", xp=XP_PER_LESSON)]
    chart = candle_chart(_candles(db, LESSON_CHART_SYMBOL, now_ms), title=f"{LESSON_CHART_SYMBOL} · {CHART_TIMEFRAME}")
    return _post("lesson", day_key(now_ms), lines, bot_username, chart)


def _public_review(db: Session, position: Position, now_ms: int) -> dict:
    # A detached free player: AI opinions in the review keep the one-hour delay.
    return trade_review(db, Player(is_pro_until=None), position, now_ms)


def _note_lines(review: dict) -> list[str]:
    return [_(f"channel.note.{code}") for code in review["notes"]]


def _player_rows(table, banned: set[int], limit: int) -> list[str]:
    rows = [row for row in table if row.rank is not None and row.player_id not in banned][:limit]
    return [_("channel.row", place=place, nickname=escape(row.nickname), ret=row.return_pct)
            for place, row in enumerate(rows, start=1)]


def _best_ai(table) -> str | None:
    ai_rows = [row for row in table if row.is_ai]
    if not ai_rows:
        return None
    best = max(ai_rows, key=lambda row: row.return_pct)
    return _("channel.best_ai", nickname=escape(best.nickname), ret=best.return_pct)


def evening_post(db: Session, quotes: QuoteBook, now_ms: int, bot_username: str) -> Post | None:
    """The UTC day so far: how many traded, sprint top 3, best AI and the trade of the day."""
    day_start = now_ms - now_ms % DAY_MS
    banned = _banned_ids(db)
    traders = {
        player_id
        for (player_id,) in db.query(Portfolio.player_id)
        .join(Fill, Fill.portfolio_id == Portfolio.id)
        .join(Player, Player.id == Portfolio.player_id)
        .filter(Fill.is_user.is_(True), Fill.created_at >= day_start, Fill.created_at <= now_ms, Player.is_ai.is_(False))
    } - banned
    if not traders:
        return None

    lines = [_("channel.evening.title"), "", _("channel.evening.traders", count=len(traders))]
    sprint = (
        db.query(Season)
        .filter(Season.kind == SeasonKind.SPRINT.value, Season.starts_at <= now_ms, Season.ends_at > now_ms)
        .order_by(Season.starts_at.desc())
        .first()
    )
    if sprint is not None:
        table = standings(db, sprint, quotes, now_ms)
        top = _player_rows(table, banned, TOP_DAY)
        if top:
            lines += ["", _("channel.evening.top"), *top]
        best_ai = _best_ai(table)
        if best_ai:
            lines.append(best_ai)

    candidates = (
        db.query(Position, Player)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .join(Player, Player.id == Portfolio.player_id)
        .filter(Position.closed_at >= day_start, Position.closed_at <= now_ms, Position.pnl > 0, Player.is_ai.is_(False))
        .all()
    )
    candidates = [(position, player) for position, player in candidates if player.id not in banned]
    if candidates:
        position, player = max(candidates, key=lambda item: (item[0].pnl / item[0].reserved, -item[0].id))
        review = _public_review(db, position, now_ms)
        lines += ["", _("channel.evening.trade_title"),
                  _("channel.evening.trade", nickname=escape(player.nickname), side=_(f"channel.side.{position.side}"),
                    symbol=position.symbol, pnl_pct=review["result"]["pnl_pct"],
                    reason=_(f"channel.reason.{position.close_reason}")),
                  *_note_lines(review)]
    return _post("evening", day_key(now_ms), lines, bot_username)


def season_post(db: Session, season: Season, quotes: QuoteBook, now_ms: int, bot_username: str) -> Post | None:
    """Finished season: top 5, best AI, how many beat it, season badges."""
    banned = _banned_ids(db)
    table = standings(db, season, quotes, now_ms)
    ranked = [row for row in table if row.rank is not None and row.player_id not in banned]
    if not ranked:
        return None

    lines = [_("channel.season.title", season=_(f"season.{season.kind}")), "", _("channel.season.top"),
             *_player_rows(table, banned, TOP_SEASON)]
    best_ai = _best_ai(table)
    if best_ai:
        best_return = max(row.return_pct for row in table if row.is_ai)
        lines += ["", best_ai,
                  _("channel.season.beat_ai", beat=sum(row.return_pct > best_return for row in ranked), total=len(ranked))]
    for code in CHANNEL_BADGES:
        names = [
            escape(nickname)
            for (nickname,) in db.query(Player.nickname)
            .join(Badge, Badge.player_id == Player.id)
            .filter(Badge.season_id == season.id, Badge.code == code)
            .order_by(Player.nickname)
        ]
        if names:
            lines += ["", f"{_(f'channel.badge.{code}')} {', '.join(names)}"]
    lines += ["", _("channel.season.outro")]
    return _post("season", str(season.id), lines, bot_username)


def ai_move_post(db: Session, season: Season, now_ms: int, bot_username: str) -> Post | None:
    """Week season: the AI trade with the biggest pnl, even a losing one, with a chart of it."""
    if season.kind != SeasonKind.WEEK.value:
        return None
    best = (
        db.query(Position, Player)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .join(Player, Player.id == Portfolio.player_id)
        .filter(Portfolio.season_id == season.id, Player.is_ai.is_(True), Position.closed_at.isnot(None))
        .order_by(Position.pnl.desc(), Position.id)
        .first()
    )
    if best is None:
        return None
    position, ai = best
    review = _public_review(db, position, now_ms)
    lines = [_("channel.ai_move.title"), "",
             _("channel.ai_move.trade", nickname=escape(ai.nickname), side=_(f"channel.side.{position.side}"),
               symbol=position.symbol, entry=_price(position.entry_price), exit=_price(position.exit_price),
               pnl_pct=review["result"]["pnl_pct"], reason=_(f"channel.reason.{position.close_reason}")),
             *_note_lines(review), "", _("channel.ai_move.outro")]
    candles = _candles(db, position.symbol, position.closed_at + HOUR_MS, since_ms=position.opened_at - 2 * HOUR_MS,
                       limit=AI_MOVE_MAX_CANDLES)
    markers = [(position.opened_at, position.entry_price, "entry"), (position.closed_at, position.exit_price, "exit")]
    chart = candle_chart(candles, title=f"{position.symbol} · {CHART_TIMEFRAME}", markers=markers)
    return _post("ai_move", str(season.id), lines, bot_username, chart)
