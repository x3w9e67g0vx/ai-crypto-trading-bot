from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.game_deps import current_player, get_now_ms, get_quotes
from app.core.db.dependencies import get_db
from app.core.db.models import Candle
from app.game.ai_view import is_pro
from app.game.config import (
    CHART_TIMEFRAME,
    GAME_SYMBOLS,
    MAX_TRADES_PER_DAY,
    STALE_AFTER_MS,
    STARTING_BALANCE,
    SeasonKind,
)
from app.game.errors import UnknownSymbol
from app.game.models import Badge, Player, Portfolio
from app.game.players import unlocked_symbols, validate_nickname
from app.game.quotes import QuoteBook
from app.game.seasons import ensure_current_season, join_season
from app.game.trading import portfolio_value, user_trades_today

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
