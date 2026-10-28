from __future__ import annotations

from sqlalchemy.orm import Session

from app.game.config import (
    DAY_MS,
    FEE_RATE,
    GAME_SYMBOLS,
    MAX_PAIR_SHARE,
    MAX_TRADES_PER_DAY,
    XP_PER_TRADE,
)
from app.game.errors import (
    DailyTradeLimit,
    InsufficientFunds,
    InvalidAmount,
    InvalidStops,
    PairLimitExceeded,
    PositionExists,
    PositionNotFound,
    SeasonClosed,
    UnknownSymbol,
)
from app.game.models import Fill, Portfolio, Position, Season
from app.game.progress import award_xp
from app.game.quotes import QuoteBook

SIDES = ("long", "short")


def open_positions(portfolio: Portfolio) -> list[Position]:
    return [position for position in portfolio.positions if position.closed_at is None]


def _mark_prices(position: Position, quotes: QuoteBook, now_ms: int, allow_stale: bool) -> tuple[float, float]:
    if allow_stale:
        quote = quotes.last(position.symbol)
        if quote is None:
            return position.entry_price, position.entry_price
        return quote.bid, quote.ask
    quote = quotes.get(position.symbol, now_ms)
    return quote.bid, quote.ask


def position_value(position: Position, bid: float, ask: float) -> float:
    """What closing now would return to cash, before the exit fee."""
    if position.side == "long":
        return position.qty * bid
    return position.reserved + (position.entry_price - ask) * position.qty


def portfolio_value(
    portfolio: Portfolio,
    quotes: QuoteBook,
    now_ms: int,
    *,
    allow_stale: bool = False,
) -> float:
    value = portfolio.cash
    for position in open_positions(portfolio):
        bid, ask = _mark_prices(position, quotes, now_ms, allow_stale)
        value += position_value(position, bid, ask)
    return value


def user_trades_today(db: Session, portfolio: Portfolio, now_ms: int) -> int:
    day_start = now_ms - now_ms % DAY_MS
    return (
        db.query(Fill)
        .filter(
            Fill.portfolio_id == portfolio.id,
            Fill.is_user.is_(True),
            Fill.created_at >= day_start,
            Fill.created_at < day_start + DAY_MS,
        )
        .count()
    )


def _check_daily_limit(db: Session, portfolio: Portfolio, now_ms: int) -> None:
    if user_trades_today(db, portfolio, now_ms) >= MAX_TRADES_PER_DAY:
        raise DailyTradeLimit(portfolio.id)


def _validate_stops(side: str, bid: float, ask: float, stop_loss: float | None, take_profit: float | None) -> None:
    if side == "long":
        ok = (stop_loss is None or stop_loss < ask) and (take_profit is None or take_profit > ask)
    else:
        ok = (stop_loss is None or stop_loss > bid) and (take_profit is None or take_profit < bid)
    if not ok:
        raise InvalidStops(side)


def open_position(
    db: Session,
    portfolio: Portfolio,
    symbol: str,
    side: str,
    amount_usdt: float,
    quotes: QuoteBook,
    now_ms: int,
    *,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    is_user: bool = True,
) -> Position:
    if portfolio.season.status != "active":
        raise SeasonClosed(portfolio.season_id)
    if symbol not in GAME_SYMBOLS:
        raise UnknownSymbol(symbol)
    if side not in SIDES or not amount_usdt > 0:
        raise InvalidAmount(amount_usdt)
    if any(position.symbol == symbol for position in open_positions(portfolio)):
        raise PositionExists(symbol)
    if is_user:
        _check_daily_limit(db, portfolio, now_ms)

    quote = quotes.get(symbol, now_ms)
    _validate_stops(side, quote.bid, quote.ask, stop_loss, take_profit)

    if amount_usdt > MAX_PAIR_SHARE * portfolio_value(portfolio, quotes, now_ms, allow_stale=True):
        raise PairLimitExceeded(symbol)
    fee = amount_usdt * FEE_RATE
    if portfolio.cash < amount_usdt + fee:
        raise InsufficientFunds(portfolio.id)

    price = quote.ask if side == "long" else quote.bid
    position = Position(
        symbol=symbol,
        side=side,
        qty=amount_usdt / price,
        entry_price=price,
        reserved=amount_usdt,
        stop_loss=stop_loss,
        take_profit=take_profit,
        opened_at=now_ms,
    )
    portfolio.positions.append(position)
    portfolio.cash -= amount_usdt + fee
    portfolio.trades_count += 1
    db.flush()
    db.add(
        Fill(
            portfolio_id=portfolio.id,
            position_id=position.id,
            symbol=symbol,
            side="buy" if side == "long" else "sell",
            qty=position.qty,
            price=price,
            fee=fee,
            is_user=is_user,
            created_at=now_ms,
        )
    )
    db.flush()
    return position


def close_position(
    db: Session,
    position: Position,
    quotes: QuoteBook,
    now_ms: int,
    *,
    reason: str = "manual",
    is_user: bool = True,
) -> Position:
    if position.closed_at is not None:
        raise PositionNotFound(position.id)
    portfolio = position.portfolio
    status = portfolio.season.status
    if status in ("finished", "voided") or (status in ("closing", "voiding") and reason != "season_end"):
        raise SeasonClosed(portfolio.season_id)
    if is_user:
        _check_daily_limit(db, portfolio, now_ms)

    quote = quotes.get(position.symbol, now_ms)
    price = quote.bid if position.side == "long" else quote.ask
    fee = position.qty * price * FEE_RATE
    proceeds = position_value(position, quote.bid, quote.ask) - fee

    portfolio.cash += proceeds
    portfolio.trades_count += 1
    award_xp(portfolio.player, XP_PER_TRADE)
    position.closed_at = now_ms
    position.exit_price = price
    position.close_reason = reason
    position.pnl = proceeds - position.reserved * (1 + FEE_RATE)
    db.add(
        Fill(
            portfolio_id=portfolio.id,
            position_id=position.id,
            symbol=position.symbol,
            side="sell" if position.side == "long" else "buy",
            qty=position.qty,
            price=price,
            fee=fee,
            is_user=is_user,
            created_at=now_ms,
        )
    )
    db.flush()
    return position


def _stop_reason(position: Position, bid: float, ask: float) -> str | None:
    mark = bid if position.side == "long" else ask
    sign = 1 if position.side == "long" else -1
    if position.stop_loss is not None and sign * (mark - position.stop_loss) <= 0:
        return "stop_loss"
    if position.take_profit is not None and sign * (mark - position.take_profit) >= 0:
        return "take_profit"
    return None


def check_stops(db: Session, quotes: QuoteBook, now_ms: int) -> list[Position]:
    candidates = (
        db.query(Position)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .join(Season, Portfolio.season_id == Season.id)
        .filter(
            Season.status == "active",
            Position.closed_at.is_(None),
            (Position.stop_loss.isnot(None)) | (Position.take_profit.isnot(None)),
        )
        .order_by(Position.id)
        .all()
    )
    closed = []
    for position in candidates:
        if not quotes.is_fresh(position.symbol, now_ms):
            continue
        quote = quotes.get(position.symbol, now_ms)
        reason = _stop_reason(position, quote.bid, quote.ask)
        if reason is not None:
            closed.append(close_position(db, position, quotes, now_ms, reason=reason, is_user=False))
    return closed
