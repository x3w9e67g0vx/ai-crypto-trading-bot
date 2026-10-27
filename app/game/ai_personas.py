from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.game.config import FEE_RATE, MAX_PAIR_SHARE
from app.game.models import Player, Portfolio
from app.game.quotes import QuoteBook
from app.game.trading import portfolio_value


@dataclass(frozen=True)
class Persona:
    key: str  # Player.ai_key and the model_type the signal comes from
    nickname: str
    buy_threshold: float
    sell_threshold: float
    position_fraction: float
    stop_loss_pct: float
    take_profit_pct: float
    use_trend_filter: bool


# Starting values from the spec; tuned during the beta.
PERSONAS = (
    Persona("lstm", "LSTM", 0.55, 0.45, 0.40, 0.03, 0.06, True),
    Persona("random_forest", "Random Forest", 0.65, 0.35, 0.15, 0.015, 0.03, True),
    # The spec gives the "newbie" no SL/TP of its own; it reuses LSTM's.
    Persona("logistic_regression", "LogReg", 0.55, 0.45, 0.25, 0.03, 0.06, False),
)


@dataclass(frozen=True)
class Signal:
    """A model's opinion on the candle that opened at candle_ts."""

    candle_ts: int
    probability_up: float
    ema_fast: float | None
    ema_slow: float | None


def view(persona: Persona, signal: Signal) -> str:
    bullish = signal.probability_up >= persona.buy_threshold
    bearish = signal.probability_up <= persona.sell_threshold
    if persona.use_trend_filter:
        if signal.ema_fast is None or signal.ema_slow is None:
            return "neutral"
        bullish = bullish and signal.ema_fast > signal.ema_slow
        bearish = bearish and signal.ema_fast < signal.ema_slow
    if bullish:
        return "bullish"
    if bearish:
        return "bearish"
    return "neutral"


def decide(stance: str, open_side: str | None) -> str:
    """An opposite view closes the position first; a new one opens on the next candle."""
    wanted = {"bullish": "long", "bearish": "short"}.get(stance)
    if wanted is None or open_side == wanted:
        return "hold"
    if open_side is not None:
        return "close"
    return f"open_{wanted}"


def order_size(persona: Persona, portfolio: Portfolio, quotes: QuoteBook, now_ms: int) -> float:
    value = portfolio_value(portfolio, quotes, now_ms, allow_stale=True)
    return min(
        persona.position_fraction * value,
        MAX_PAIR_SHARE * value,
        portfolio.cash / (1 + FEE_RATE),
    )


def stop_prices(persona: Persona, side: str, bid: float, ask: float) -> tuple[float, float]:
    """(stop_loss, take_profit) around the price the position opens at."""
    if side == "long":
        return ask * (1 - persona.stop_loss_pct), ask * (1 + persona.take_profit_pct)
    return bid * (1 + persona.stop_loss_pct), bid * (1 - persona.take_profit_pct)


def ensure_ai_players(db: Session, now_ms: int) -> dict[str, Player]:
    players = {player.ai_key: player for player in db.query(Player).filter_by(is_ai=True)}
    for persona in PERSONAS:
        if persona.key not in players:
            player = Player(nickname=persona.nickname, is_ai=True, ai_key=persona.key, created_at=now_ms)
            db.add(player)
            players[persona.key] = player
    db.flush()
    return {persona.key: players[persona.key] for persona in PERSONAS}
