from __future__ import annotations

import hmac
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.game_deps import current_player, get_now_ms, get_quotes
from app.core.config import settings
from app.core.db.dependencies import get_db
from app.core.db.models import Candle
from app.game.ai_personas import PERSONAS
from app.game.analytics import log_event
from app.game.charts import share_card
from app.game.ai_view import ai_decisions_view, ai_positions_view, is_pro
from app.game.config import (
    CHART_TIMEFRAME,
    FEE_RATE,
    GAME_SYMBOLS,
    PRO_SYMBOLS,
    MAX_TRADES_PER_DAY,
    STALE_AFTER_MS,
    DUEL_KIND,
    STARTING_BALANCE,
    WEEKEND_KIND,
    XP_PER_LESSON,
    SeasonKind,
)
from app.game.duels import cancel_duel, create_duel, duel_link, duel_portfolio, duel_view
from app.game.errors import (
    DuelNotFound,
    LessonNotFound,
    PositionExists,
    PositionNotFound,
    SymbolLocked,
    UnknownSymbol,
    WeekendNotRunning,
)
from app.game.insights import ai_entry_why, indicators_at, order_tips, trade_review
from app.game.leaderboard import standings
from app.game.llm_review import llm_review
from app.game.shop import SLOTS, equip, wardrobe, worn
from app.game.leagues import group_portfolio_ids
from app.game.lessons import Lesson, get_lesson, get_lessons
from app.game.models import Badge, Player, Portfolio, Position
from app.game.players import unlocked_symbols, validate_nickname
from app.game.guesses import guess_view, make_guess
from app.game.puzzle import answer_puzzle, puzzle_view
from app.game.replay import finish_replay, finish_scenario, replay_view, scenario_view
from app.game.quests import claim_quests
from app.game.progress import complete_lesson, completed_lessons, level_info
from app.game.quotes import QuoteBook
from app.game.referrals import ref_link
from app.game.seasons import current_portfolio, ensure_current_season
from app.game.streaks import claim_streak
from app.game.weekend import ensure_weekend, weekend_info, weekend_portfolio
from app.game.share import card_sig, share_info, share_text
from app.i18n.strings import t
from app.game.trading import (
    close_position,
    open_position,
    portfolio_value,
    position_value,
    user_trades_today,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/game", tags=["game"])

SeasonParam = Literal["sprint", "week"]
# Screens that also show the running friend duel and weekend tournament.
PlaySeason = Literal["sprint", "week", "duel", "weekend"]


def _play_portfolio(db: Session, player: Player, season: str, now_ms: int) -> Portfolio:
    if season == WEEKEND_KIND:
        portfolio = weekend_portfolio(db, player, now_ms)
        if portfolio is None:
            raise WeekendNotRunning()
        return portfolio
    if season != DUEL_KIND:
        return current_portfolio(db, player, season, now_ms)
    portfolio = duel_portfolio(db, player, now_ms)
    if portfolio is None:
        raise DuelNotFound()
    return portfolio


def _player_json(db: Session, player: Player, now_ms: int) -> dict:
    badges = db.query(Badge).filter_by(player_id=player.id).order_by(Badge.created_at).all()
    level = level_info(player.xp)
    return {
        "id": player.id,
        "nickname": player.nickname,
        "language": player.language,
        "league_tier": player.league_tier,
        "xp": player.xp,
        "level": level.level,
        "level_xp": level.level_xp,
        "next_level_xp": level.next_level_xp,
        "next_unlocks": list(level.next_unlocks),
        "is_pro": is_pro(player, now_ms),
        "pro_until": player.is_pro_until if is_pro(player, now_ms) else None,
        "cosmetics": worn(player, now_ms),
        "wardrobe": wardrobe(db, player, now_ms),
        "shop_link": f"https://t.me/{settings.BOT_USERNAME}?start=pro" if settings.BOT_USERNAME else None,
        "needs_nickname": not player.nickname_set,
        "badges": [{"code": badge.code, "season_id": badge.season_id} for badge in badges],
    }


def _portfolio_json(db: Session, portfolio: Portfolio, quotes: QuoteBook, now_ms: int) -> dict:
    value = portfolio_value(portfolio, quotes, now_ms, allow_stale=True)
    return {
        "season_id": portfolio.season_id,
        "starts_at": portfolio.season.starts_at,
        "ends_at": portfolio.season.ends_at,
        "cash": portfolio.cash,
        "value": value,
        "return_pct": (value / STARTING_BALANCE - 1) * 100,
        "trades": portfolio.trades_count,
        "trades_today": user_trades_today(db, portfolio, now_ms),
        "trades_limit": MAX_TRADES_PER_DAY,
    }


def _me_json(db: Session, player: Player, quotes: QuoteBook, now_ms: int) -> dict:
    portfolios = {kind.value: current_portfolio(db, player, kind.value, now_ms) for kind in SeasonKind}
    duel = duel_portfolio(db, player, now_ms)
    if duel is not None:
        portfolios[DUEL_KIND] = duel
    weekend = weekend_portfolio(db, player, now_ms)
    if weekend is not None:
        portfolios[WEEKEND_KIND] = weekend
    weekend_card = weekend_info(db, player, now_ms)
    weekend_card["link"] = f"https://t.me/{settings.BOT_USERNAME}?start=weekend" if settings.BOT_USERNAME else None
    streak = claim_streak(db, player, now_ms)
    db.commit()
    return {
        "player": _player_json(db, player, now_ms),
        "streak": streak,
        "weekend": weekend_card,
        "portfolios": {
            kind: _portfolio_json(db, portfolio, quotes, now_ms) for kind, portfolio in portfolios.items()
        },
    }


class ProfileUpdate(BaseModel):
    nickname: str | None = None
    language: Literal["ru", "en"] | None = None
    # Sent as null: take the cosmetic off; left out: unchanged.
    frame: str | None = None
    nick_color: str | None = None
    ai_skin: str | None = None


@router.get("/me")
def get_me(
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    log_event(db, player, "return", now_ms, once_per_day=True)
    return _me_json(db, player, quotes, now_ms)


@router.patch("/me")
def update_me(
    update: ProfileUpdate,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    if update.nickname is not None:
        player.nickname = validate_nickname(db, player, update.nickname)
        player.nickname_set = True
    if update.language is not None:
        player.language = update.language
    for slot in SLOTS:
        if slot in update.model_fields_set:
            equip(db, player, slot, getattr(update, slot), now_ms)
    db.commit()
    return _me_json(db, player, quotes, now_ms)


def _quote_json(symbol: str, quotes: QuoteBook, now_ms: int) -> dict:
    quote = quotes.last(symbol)
    if quote is None:
        return {"symbol": symbol, "bid": None, "ask": None, "ts": None, "fresh": False}
    return {
        "symbol": symbol,
        "bid": quote.bid,
        "ask": quote.ask,
        "ts": quote.ts,
        "fresh": quotes.is_fresh(symbol, now_ms),
    }


@router.get("/quotes")
def get_market_quotes(
    player: Player = Depends(current_player),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    symbols = unlocked_symbols(player, now_ms)
    last_update = quotes.last_update_ms()
    return {
        "source": "binance",
        "exchange_down": last_update is None or now_ms - last_update > STALE_AFTER_MS,
        "symbols": list(symbols),
        "pro_symbols": list(PRO_SYMBOLS),
        "quotes": [_quote_json(symbol, quotes, now_ms) for symbol in symbols],
    }


@router.get("/candles")
def get_candles(
    symbol: str,
    limit: int = Query(default=300, ge=1, le=1000),
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
) -> list[dict]:
    if symbol not in GAME_SYMBOLS:
        raise UnknownSymbol(symbol)
    rows = (
        db.query(Candle)
        .filter_by(symbol=symbol, timeframe=CHART_TIMEFRAME)
        .order_by(Candle.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {"time": row.timestamp // 1000, "open": row.open, "high": row.high, "low": row.low, "close": row.close}
        for row in reversed(rows)
    ]


def _position_json(position: Position, quotes: QuoteBook) -> dict:
    row = {
        "id": position.id,
        "symbol": position.symbol,
        "side": position.side,
        "qty": position.qty,
        "entry_price": position.entry_price,
        "reserved": position.reserved,
        "stop_loss": position.stop_loss,
        "take_profit": position.take_profit,
        "opened_at": position.opened_at,
        "closed_at": position.closed_at,
        "exit_price": position.exit_price,
        "pnl": position.pnl,
        "close_reason": position.close_reason,
    }
    quote = quotes.last(position.symbol)
    if position.closed_at is None and quote is not None:
        # What closing at the last known price would give, both fees included (like `pnl`).
        mark = quote.bid if position.side == "long" else quote.ask
        value = position_value(position, quote.bid, quote.ask)
        row["value"] = value
        row["unrealized_pnl"] = value - position.qty * mark * FEE_RATE - position.reserved * (1 + FEE_RATE)
    return row


class OrderRequest(BaseModel):
    season: PlaySeason
    symbol: str
    side: Literal["long", "short"]
    amount_usdt: float
    stop_loss: float | None = None
    take_profit: float | None = None


@router.post("/orders")
def place_order(
    order: OrderRequest,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    if order.symbol not in GAME_SYMBOLS:
        raise UnknownSymbol(order.symbol)
    if order.symbol not in unlocked_symbols(player, now_ms):
        raise SymbolLocked(order.symbol)
    portfolio = _play_portfolio(db, player, order.season, now_ms)
    value_before = portfolio_value(portfolio, quotes, now_ms, allow_stale=True)
    try:
        position = open_position(
            db,
            portfolio,
            order.symbol,
            order.side,
            order.amount_usdt,
            quotes,
            now_ms,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
        )
        db.commit()
    except IntegrityError:
        # A parallel order for the same pair won the race (unique open-position index).
        db.rollback()
        raise PositionExists(order.symbol)
    try:
        log_event(db, player, "trade", now_ms)
        db.commit()
    except SQLAlchemyError:
        # Analytics must never fail a trade that is already committed.
        db.rollback()
        logger.exception("failed to log trade event")
    try:
        tips = order_tips(db, player, position, indicators_at(db, order.symbol, now_ms), value_before, now_ms)
        db.commit()
    except Exception:
        # Micro lessons are a hint; the trade is already committed.
        db.rollback()
        logger.exception("failed to build order tips")
        tips = []
    return {**_position_json(position, quotes), "tips": tips}


@router.post("/positions/{position_id}/close")
def close_my_position(
    position_id: int,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    position = (
        db.query(Position)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .filter(Position.id == position_id, Portfolio.player_id == player.id)
        .one_or_none()
    )
    if position is None:
        raise PositionNotFound(position_id)
    close_position(db, position, quotes, now_ms)
    db.commit()
    return _position_json(position, quotes)


@router.get("/positions/{position_id}/review")
def review_my_position(
    position_id: int,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    """Template review of the player's own closed position."""
    position = (
        db.query(Position)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .filter(Position.id == position_id, Portfolio.player_id == player.id, Position.closed_at.isnot(None))
        .one_or_none()
    )
    if position is None:
        raise PositionNotFound(position_id)
    return trade_review(db, player, position, now_ms)


@router.post("/positions/{position_id}/review/llm")
def llm_review_my_position(
    position_id: int,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    """Pro: coach text on the player's own closed position, cached after the first call."""
    position = (
        db.query(Position)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .filter(Position.id == position_id, Portfolio.player_id == player.id, Position.closed_at.isnot(None))
        .one_or_none()
    )
    if position is None:
        raise PositionNotFound(position_id)
    return {"position_id": position.id, "text": llm_review(db, player, position, now_ms)}


@router.get("/positions")
def list_positions(
    season: PlaySeason,
    status: Literal["open", "closed"] = "open",
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> list[dict]:
    portfolio = _play_portfolio(db, player, season, now_ms)
    db.commit()
    query = db.query(Position).filter(Position.portfolio_id == portfolio.id)
    if status == "open":
        query = query.filter(Position.closed_at.is_(None)).order_by(Position.opened_at)
    else:
        query = query.filter(Position.closed_at.isnot(None)).order_by(Position.closed_at.desc())
    return [_position_json(position, quotes) for position in query.all()]


LEADERBOARD_TOP = 100


@router.get("/leaderboard")
def get_leaderboard(
    season: PlaySeason,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    """Week: the player's league group (AI ghosts included); sprint: everyone."""
    portfolio = _play_portfolio(db, player, season, now_ms)
    db.commit()
    group, portfolio_ids = group_portfolio_ids(db, portfolio)
    table = standings(db, portfolio.season, quotes, now_ms, portfolio_ids=portfolio_ids)
    players = {p.id: p for p in db.query(Player).filter(Player.id.in_([row.player_id for row in table]))}

    rows = [
        {
            "rank": row.rank,
            "nickname": row.nickname,
            "is_ai": row.is_ai,
            "return_pct": row.return_pct,
            "trades": row.trades,
            "qualified": row.qualified,
            "drawdown_pct": row.drawdown_pct,
            "stop_share": row.stop_share,
            "quality": row.quality,
            "is_me": row.portfolio_id == portfolio.id,
            **{slot: code for slot, code in worn(players[row.player_id], now_ms).items() if slot != "ai_skin"},
        }
        for row in table
    ]
    shown = rows[:LEADERBOARD_TOP] + [row for row in rows[LEADERBOARD_TOP:] if row["is_me"]]
    return {
        "season_id": portfolio.season_id,
        "scope": "group" if group is not None else "global",
        "tier": group.tier if group is not None else None,
        "rows": shown,
    }


@router.get("/ai")
def get_ai_players(
    season: Literal["sprint", "week", "weekend"],
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> list[dict]:
    """AI personas with positions and opinions, delayed for non-Pro viewers."""
    season_row = ensure_weekend(db, now_ms) if season == WEEKEND_KIND else ensure_current_season(db, SeasonKind(season), now_ms)
    db.commit()
    ai_players = {row.ai_key: row for row in db.query(Player).filter_by(is_ai=True)}
    result = []
    for persona in PERSONAS:
        ai_player = ai_players.get(persona.key)
        if ai_player is None:
            continue
        portfolio = db.query(Portfolio).filter_by(player_id=ai_player.id, season_id=season_row.id).one_or_none()
        positions = ai_positions_view(db, player, portfolio, now_ms) if portfolio is not None else []
        value = portfolio_value(portfolio, quotes, now_ms, allow_stale=True) if portfolio is not None else STARTING_BALANCE
        result.append(
            {
                "key": persona.key,
                "nickname": ai_player.nickname,
                "return_pct": (value / STARTING_BALANCE - 1) * 100,
                "delayed": not is_pro(player, now_ms),
                "positions": [
                    {
                        "id": position.id,
                        "symbol": position.symbol,
                        "side": position.side,
                        "entry_price": position.entry_price,
                        "stop_loss": position.stop_loss,
                        "take_profit": position.take_profit,
                        "opened_at": position.opened_at,
                    }
                    for position in positions
                ],
                "decisions": [
                    {
                        "symbol": decision.symbol,
                        "candle_ts": decision.candle_ts,
                        "probability_up": decision.probability_up,
                        "view": decision.view,
                        "created_at": decision.created_at,
                    }
                    for decision in ai_decisions_view(db, player, ai_player, now_ms)
                ],
            }
        )
    return result


@router.get("/ai/positions/{position_id}/why")
def get_ai_position_why(
    position_id: int,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    """Why an AI opened this position; 404 until the viewer may see it."""
    why = ai_entry_why(db, player, position_id, now_ms)
    if why is None:
        raise PositionNotFound(position_id)
    return why


def _lesson_or_404(player: Player, lesson_id: str) -> Lesson:
    lesson = get_lesson(player.language, lesson_id)
    if lesson is None:
        raise LessonNotFound(lesson_id)
    return lesson


@router.get("/lessons")
def list_lessons(player: Player = Depends(current_player), db: Session = Depends(get_db)) -> list[dict]:
    done = completed_lessons(db, player)
    return [
        {"id": lesson.id, "title": lesson.title, "done": lesson.id in done, "xp": XP_PER_LESSON}
        for lesson in get_lessons(player.language)
    ]


@router.get("/lessons/{lesson_id}")
def read_lesson(lesson_id: str, player: Player = Depends(current_player), db: Session = Depends(get_db)) -> dict:
    lesson = _lesson_or_404(player, lesson_id)
    return {
        "id": lesson.id,
        "title": lesson.title,
        "done": lesson.id in completed_lessons(db, player),
        "blocks": list(lesson.blocks),
        "question": lesson.question,
        "options": list(lesson.options),
    }


class LessonAnswer(BaseModel):
    answer: int


@router.post("/lessons/{lesson_id}/complete")
def pass_lesson(
    lesson_id: str,
    body: LessonAnswer,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    lesson = _lesson_or_404(player, lesson_id)
    xp_awarded = complete_lesson(db, player, lesson, body.answer, now_ms)
    db.commit()
    return {"xp_awarded": xp_awarded, "player": _player_json(db, player, now_ms)}


@router.get("/puzzle")
def get_puzzle(
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    view = puzzle_view(db, player, now_ms)
    db.commit()
    return {"puzzle": view}


class PuzzleAnswerRequest(BaseModel):
    choice: Literal["long", "short", "skip"]


@router.post("/puzzle")
def post_puzzle(
    body: PuzzleAnswerRequest,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    xp_awarded = answer_puzzle(db, player, body.choice, now_ms)
    db.commit()
    return {"xp_awarded": xp_awarded, "puzzle": puzzle_view(db, player, now_ms), "player": _player_json(db, player, now_ms)}


@router.get("/replay")
def get_replay(
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    return {"replay": replay_view(db, now_ms)}


@router.post("/replay/finish")
def post_replay_finish(
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    xp_awarded = finish_replay(db, player, now_ms)
    db.commit()
    return {"xp_awarded": xp_awarded, "player": _player_json(db, player, now_ms)}


ScenarioKind = Literal["crash", "pump_dump", "flat"]


@router.get("/scenario")
def get_scenario(
    kind: ScenarioKind,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    return {"scenario": scenario_view(db, now_ms, kind)}


class ScenarioFinishRequest(BaseModel):
    passed: bool


@router.post("/scenario/finish")
def post_scenario_finish(
    body: ScenarioFinishRequest,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    xp_awarded = finish_scenario(db, player, body.passed, now_ms)
    db.commit()
    return {"xp_awarded": xp_awarded, "player": _player_json(db, player, now_ms)}


@router.get("/guess")
def get_guess(
    symbol: str,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    view = guess_view(db, player, symbol, now_ms)
    db.commit()
    return {"guess": view, "player": _player_json(db, player, now_ms)}


class GuessRequest(BaseModel):
    symbol: str
    price: Literal["up", "down"]
    view: Literal["bullish", "bearish", "neutral"]


@router.post("/guess")
def post_guess(
    body: GuessRequest,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    make_guess(db, player, body.symbol, body.price, body.view, now_ms)
    view = guess_view(db, player, body.symbol, now_ms)
    db.commit()
    return {"guess": view, "player": _player_json(db, player, now_ms)}


def _duel_json(db: Session, player: Player, quotes: QuoteBook, now_ms: int) -> dict:
    view = duel_view(db, player, quotes, now_ms)
    if view["state"] == "open" and settings.BOT_USERNAME:
        view["link"] = duel_link(settings.BOT_USERNAME, view["id"])
        view["text"] = t("duel.share", lang=player.language)
    return view


@router.get("/duel")
def get_duel(
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    return _duel_json(db, player, quotes, now_ms)


@router.post("/duel")
def post_duel(
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    """Challenge a friend: returns the invite link (the same one while it is open)."""
    create_duel(db, player, now_ms)
    db.commit()
    return _duel_json(db, player, quotes, now_ms)


@router.delete("/duel")
def delete_duel(
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    cancel_duel(db, player, now_ms)
    db.commit()
    return _duel_json(db, player, quotes, now_ms)


@router.get("/quests")
def get_quests(
    season: SeasonParam,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    portfolio = current_portfolio(db, player, season, now_ms)
    rows, xp_awarded = claim_quests(db, portfolio, now_ms)
    db.commit()
    return {"quests": rows, "xp_awarded": xp_awarded, "player": _player_json(db, player, now_ms)}


class ShareRequest(BaseModel):
    season: SeasonParam


@router.post("/share")
def share(
    request: ShareRequest,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    """Share text, referral link and a signed link to the card picture."""
    portfolio = current_portfolio(db, player, request.season, now_ms)
    info = share_info(db, portfolio, quotes, now_ms)
    log_event(db, player, "share", now_ms)
    db.commit()
    return {
        "text": share_text(info, request.season, player.language),
        "link": ref_link(settings.BOT_USERNAME, player) if settings.BOT_USERNAME else None,
        "image_url": f"/game/share/{portfolio.id}.png?sig={card_sig(portfolio.id)}",
        "return_pct": info.return_pct,
        "rank": info.rank,
        "beat_ai_by": info.beat_ai_by,
    }


CARD_MAX_AGE_S = 300


@router.get("/share/{portfolio_id}.png")
def share_card_png(
    portfolio_id: int,
    sig: str = "",
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> Response:
    """Public (Telegram fetches it for stories), so only a signed link opens a card."""
    portfolio = db.get(Portfolio, portfolio_id)
    if (
        not hmac.compare_digest(sig.encode(), card_sig(portfolio_id).encode())
        or portfolio is None
        or portfolio.player.is_ai
        or portfolio.player.is_banned
    ):
        raise HTTPException(status_code=404)
    info = share_info(db, portfolio, quotes, now_ms)
    png = share_card(
        nickname=portfolio.player.nickname,
        season=portfolio.season.kind,
        return_pct=info.return_pct,
        rank=info.rank,
        beat_ai_by=info.beat_ai_by,
        lang=portfolio.player.language,
    )
    return Response(png, media_type="image/png", headers={"Cache-Control": f"public, max-age={CARD_MAX_AGE_S}"})
