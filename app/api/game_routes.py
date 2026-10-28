from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.game_deps import current_player, get_now_ms, get_quotes
from app.core.db.dependencies import get_db
from app.core.db.models import Candle
from app.game.ai_personas import PERSONAS
from app.game.ai_view import ai_decisions_view, ai_positions_view, is_pro
from app.game.config import (
    CHART_TIMEFRAME,
    FEE_RATE,
    GAME_SYMBOLS,
    MAX_TRADES_PER_DAY,
    STALE_AFTER_MS,
    STARTING_BALANCE,
    SeasonKind,
)
from app.game.errors import PositionExists, PositionNotFound, SymbolLocked, UnknownSymbol
from app.game.leaderboard import standings
from app.game.models import Badge, LeagueGroup, LeagueMembership, Player, Portfolio, Position
from app.game.players import unlocked_symbols, validate_nickname
from app.game.quotes import QuoteBook
from app.game.seasons import ensure_current_season, join_season
from app.game.trading import (
    close_position,
    open_position,
    portfolio_value,
    position_value,
    user_trades_today,
)

router = APIRouter(prefix="/game", tags=["game"])

SeasonParam = Literal["sprint", "week"]


def current_portfolio(db: Session, player: Player, kind: str, now_ms: int) -> Portfolio:
    """The player's portfolio in the running season of this kind, joining it if needed."""
    season = ensure_current_season(db, SeasonKind(kind), now_ms)
    return join_season(db, player, season, now_ms)


def _player_json(db: Session, player: Player, now_ms: int) -> dict:
    badges = db.query(Badge).filter_by(player_id=player.id).order_by(Badge.created_at).all()
    return {
        "id": player.id,
        "nickname": player.nickname,
        "language": player.language,
        "league_tier": player.league_tier,
        "xp": player.xp,
        "is_pro": is_pro(player, now_ms),
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
    db.commit()
    return {
        "player": _player_json(db, player, now_ms),
        "portfolios": {
            kind: _portfolio_json(db, portfolio, quotes, now_ms) for kind, portfolio in portfolios.items()
        },
    }


class ProfileUpdate(BaseModel):
    nickname: str | None = None
    language: Literal["ru", "en"] | None = None


@router.get("/me")
def get_me(
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
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
    symbols = unlocked_symbols(player)
    last_update = quotes.last_update_ms()
    return {
        "source": "binance",
        "exchange_down": last_update is None or now_ms - last_update > STALE_AFTER_MS,
        "symbols": list(symbols),
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
    season: SeasonParam
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
    if order.symbol not in unlocked_symbols(player):
        raise SymbolLocked(order.symbol)
    portfolio = current_portfolio(db, player, order.season, now_ms)
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
    return _position_json(position, quotes)


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


@router.get("/positions")
def list_positions(
    season: SeasonParam,
    status: Literal["open", "closed"] = "open",
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> list[dict]:
    portfolio = current_portfolio(db, player, season, now_ms)
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
    season: SeasonParam,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> dict:
    """Week: the player's league group (AI ghosts included); sprint: everyone."""
    portfolio = current_portfolio(db, player, season, now_ms)
    db.commit()
    group = (
        db.query(LeagueGroup)
        .join(LeagueMembership, LeagueMembership.group_id == LeagueGroup.id)
        .filter(LeagueMembership.portfolio_id == portfolio.id)
        .one_or_none()
    )
    portfolio_ids = None
    if group is not None:
        portfolio_ids = [row.portfolio_id for row in db.query(LeagueMembership.portfolio_id).filter_by(group_id=group.id)]
    table = standings(db, portfolio.season, quotes, now_ms, portfolio_ids=portfolio_ids)

    rows = [
        {
            "rank": row.rank,
            "nickname": row.nickname,
            "is_ai": row.is_ai,
            "return_pct": row.return_pct,
            "trades": row.trades,
            "qualified": row.qualified,
            "is_me": row.portfolio_id == portfolio.id,
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
    season: SeasonParam,
    player: Player = Depends(current_player),
    db: Session = Depends(get_db),
    quotes: QuoteBook = Depends(get_quotes),
    now_ms: int = Depends(get_now_ms),
) -> list[dict]:
    """AI personas with positions and opinions, delayed for non-Pro viewers."""
    season_row = ensure_current_season(db, SeasonKind(season), now_ms)
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
