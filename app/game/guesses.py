"""Guess the AI: bet on the next candle's direction and on what the AIs will think of it."""
from __future__ import annotations

from collections import Counter

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.models import Candle
from app.game.config import (
    AI_SYMBOLS,
    CANDLE_TIMEFRAME,
    CANDLE_TIMEFRAME_MS,
    DAY_MS,
    GUESS_DAILY_XP_CAP,
    GUESS_GRACE_MS,
    GUESS_RECENT,
    XP_PER_GUESS_HIT,
)
from app.game.errors import AlreadyGuessed, UnknownSymbol
from app.game.models import AiDecision, AiGuess, Player
from app.game.progress import award_xp

PRICES = ("up", "down")
VIEWS = ("bullish", "bearish", "neutral")


def target_candle(now_ms: int) -> int:
    """The next candle: it has not started yet, so nothing about it can be peeked at."""
    return now_ms - now_ms % CANDLE_TIMEFRAME_MS + CANDLE_TIMEFRAME_MS


def majority_view(views: list[str]) -> str | None:
    """Most common AI view; a tie for first place counts as neutral."""
    top = Counter(views).most_common(2)
    if not top:
        return None
    if len(top) == 2 and top[0][1] == top[1][1]:
        return "neutral"
    return top[0][0]


def make_guess(db: Session, player: Player, symbol: str, price: str, view: str, now_ms: int) -> AiGuess:
    if symbol not in AI_SYMBOLS:
        raise UnknownSymbol(symbol)
    if price not in PRICES or view not in VIEWS:
        raise ValueError((price, view))
    guess = AiGuess(
        player_id=player.id, symbol=symbol, candle_ts=target_candle(now_ms), price=price, view=view, created_at=now_ms
    )
    try:
        with db.begin_nested():
            db.add(guess)
    except IntegrityError:
        raise AlreadyGuessed(symbol) from None
    return guess


def _xp_today(db: Session, player: Player, now_ms: int) -> int:
    day_start = now_ms - now_ms % DAY_MS
    total = (
        db.query(func.coalesce(func.sum(AiGuess.xp), 0))
        .filter(AiGuess.player_id == player.id, AiGuess.settled_at >= day_start)
        .scalar()
    )
    return int(total)


def settle_guesses(db: Session, player: Player, now_ms: int) -> int:
    """Settle the player's guesses on closed candles; returns XP granted now."""
    pending = (
        db.query(AiGuess)
        .filter(
            AiGuess.player_id == player.id,
            AiGuess.settled_at.is_(None),
            AiGuess.candle_ts + CANDLE_TIMEFRAME_MS <= now_ms,
        )
        .order_by(AiGuess.candle_ts, AiGuess.id)
        .all()
    )
    room = max(0, GUESS_DAILY_XP_CAP - _xp_today(db, player, now_ms))
    granted = 0
    for guess in pending:
        overdue = now_ms >= guess.candle_ts + CANDLE_TIMEFRAME_MS + GUESS_GRACE_MS
        candle = (
            db.query(Candle)
            .filter_by(symbol=guess.symbol, timeframe=CANDLE_TIMEFRAME, timestamp=guess.candle_ts)
            .one_or_none()
        )
        views = [
            view
            for (view,) in db.query(AiDecision.view)
            .join(Player, Player.id == AiDecision.player_id)
            .filter(Player.is_ai.is_(True), AiDecision.symbol == guess.symbol, AiDecision.candle_ts == guess.candle_ts)
        ]
        if (candle is None or not views) and not overdue:
            continue
        if candle is not None:
            went_up = candle.close > candle.open
            guess.price_correct = candle.close != candle.open and went_up == (guess.price == "up")
        if views:
            guess.ai_correct = guess.view == majority_view(views)
        earned = XP_PER_GUESS_HIT * (bool(guess.price_correct) + bool(guess.ai_correct))
        guess.xp = min(earned, room)
        guess.settled_at = now_ms
        room -= guess.xp
        granted += guess.xp
    award_xp(player, granted)
    db.flush()
    return granted


def _json(guess: AiGuess) -> dict:
    return {
        "symbol": guess.symbol,
        "candle_ts": guess.candle_ts,
        "price": guess.price,
        "view": guess.view,
        "price_correct": guess.price_correct,
        "ai_correct": guess.ai_correct,
        "xp": guess.xp,
    }


def guess_view(db: Session, player: Player, symbol: str, now_ms: int) -> dict:
    """Settles what can be settled, then shows the open bet on the next candle and recent results."""
    if symbol not in AI_SYMBOLS:
        raise UnknownSymbol(symbol)
    xp_awarded = settle_guesses(db, player, now_ms)
    candle_ts = target_candle(now_ms)
    current = db.query(AiGuess).filter_by(player_id=player.id, symbol=symbol, candle_ts=candle_ts).one_or_none()
    recent = (
        db.query(AiGuess)
        .filter(AiGuess.player_id == player.id, AiGuess.settled_at.isnot(None))
        .order_by(AiGuess.candle_ts.desc(), AiGuess.id.desc())
        .limit(GUESS_RECENT)
    )
    pending = db.query(AiGuess).filter_by(player_id=player.id, settled_at=None).count()
    return {
        "symbol": symbol,
        "candle_ts": candle_ts,
        "xp_per_hit": XP_PER_GUESS_HIT,
        "xp_today": _xp_today(db, player, now_ms),
        "daily_cap": GUESS_DAILY_XP_CAP,
        "current": _json(current) if current else None,
        "pending": pending,
        "recent": [_json(guess) for guess in recent],
        "xp_awarded": xp_awarded,
    }
