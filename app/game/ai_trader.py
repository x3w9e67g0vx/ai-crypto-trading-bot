from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.game.ai_personas import (
    PERSONAS,
    Persona,
    Signal,
    decide,
    ensure_ai_players,
    order_size,
    stop_prices,
    view,
)
from app.game.config import AI_MIN_ORDER_USDT, AI_SYMBOLS, SeasonKind
from app.game.errors import GameError, UnknownSymbol
from app.game.models import AiDecision, Portfolio
from app.game.quotes import QuoteBook
from app.game.seasons import ensure_current_season, join_season
from app.game.trading import close_position, open_position, open_positions

logger = logging.getLogger(__name__)


def run_ai_turn(
    db: Session,
    symbol: str,
    candle_ts: int,
    signals: dict[str, Signal],
    quotes: QuoteBook,
    now_ms: int,
) -> list[AiDecision]:
    """Let every persona with an opinion on this candle trade it in the
    current sprint and week. Safe to call again for the same candle."""
    if symbol not in AI_SYMBOLS:
        raise UnknownSymbol(symbol)
    players = ensure_ai_players(db, now_ms)
    seasons = [ensure_current_season(db, kind, now_ms) for kind in SeasonKind]

    decisions = []
    for persona in PERSONAS:
        signal = signals.get(persona.key)
        # Never trade on an older candle, e.g. when candle ingestion lags.
        if signal is None or signal.candle_ts != candle_ts:
            continue
        player = players[persona.key]
        seen = db.query(AiDecision).filter_by(player_id=player.id, symbol=symbol, candle_ts=candle_ts)
        if seen.first() is not None:
            continue

        stance = view(persona, signal)
        decision = AiDecision(
            player_id=player.id,
            symbol=symbol,
            candle_ts=candle_ts,
            probability_up=signal.probability_up,
            view=stance,
            created_at=now_ms,
        )
        db.add(decision)
        decisions.append(decision)

        for season in seasons:
            if season.status == "active":
                portfolio = join_season(db, player, season, now_ms)
                _act(db, persona, portfolio, symbol, stance, quotes, now_ms)
    db.flush()
    return decisions


def _act(
    db: Session,
    persona: Persona,
    portfolio: Portfolio,
    symbol: str,
    stance: str,
    quotes: QuoteBook,
    now_ms: int,
) -> None:
    position = next((p for p in open_positions(portfolio) if p.symbol == symbol), None)
    action = decide(stance, position.side if position else None)
    try:
        if action == "close":
            close_position(db, position, quotes, now_ms)
        elif action.startswith("open_"):
            side = action.removeprefix("open_")
            amount = order_size(persona, portfolio, quotes, now_ms)
            if amount < AI_MIN_ORDER_USDT:
                return
            quote = quotes.get(symbol, now_ms)
            stop_loss, take_profit = stop_prices(persona, side, quote.bid, quote.ask)
            open_position(
                db,
                portfolio,
                symbol,
                side,
                amount,
                quotes,
                now_ms,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
    except GameError as error:
        # Personas follow the player rules; a rejected order just skips this candle.
        logger.info(
            "AI %s skipped %s %s in portfolio %s: %s",
            persona.key,
            action,
            symbol,
            portfolio.id,
            error.code,
        )
