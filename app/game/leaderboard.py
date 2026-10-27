from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.game.config import DAY_MS, MIN_QUALIFYING_TRADES, PRIZE_MIN_ACCOUNT_AGE_DAYS, STARTING_BALANCE
from app.game.models import Badge, Player, Portfolio, PortfolioSnapshot, Position, Season
from app.game.quotes import QuoteBook
from app.game.trading import portfolio_value


@dataclass
class Standing:
    portfolio_id: int
    player_id: int
    nickname: str
    is_ai: bool
    value: float
    return_pct: float
    trades: int
    qualified: bool
    rank: int | None


def standings(
    db: Session,
    season: Season,
    quotes: QuoteBook,
    now_ms: int,
    *,
    portfolio_ids: Iterable[int] | None = None,
) -> list[Standing]:
    """Season table. AI ghosts are always listed but never take a rank."""
    query = db.query(Portfolio).join(Player).filter(Portfolio.season_id == season.id)
    if portfolio_ids is not None:
        query = query.filter(Portfolio.id.in_(list(portfolio_ids)) | Player.is_ai.is_(True))

    rows = []
    for portfolio in query.all():
        value = portfolio_value(portfolio, quotes, now_ms, allow_stale=True)
        rows.append(
            Standing(
                portfolio_id=portfolio.id,
                player_id=portfolio.player_id,
                nickname=portfolio.player.nickname,
                is_ai=portfolio.player.is_ai,
                value=value,
                return_pct=(value / STARTING_BALANCE - 1) * 100,
                trades=portfolio.trades_count,
                qualified=portfolio.trades_count >= MIN_QUALIFYING_TRADES,
                rank=None,
            )
        )
    rows.sort(key=lambda row: (not row.qualified, -row.return_pct, row.portfolio_id))

    rank = 0
    for row in rows:
        if row.qualified and not row.is_ai:
            rank += 1
            row.rank = rank
    return rows


def win_rate(db: Session, portfolio: Portfolio) -> float | None:
    closed = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio.id, Position.closed_at.isnot(None))
        .all()
    )
    if not closed:
        return None
    return sum(1 for position in closed if position.pnl > 0) / len(closed)


def max_drawdown(db: Session, portfolio: Portfolio) -> float:
    values = [STARTING_BALANCE] + [
        snapshot.value
        for snapshot in db.query(PortfolioSnapshot)
        .filter_by(portfolio_id=portfolio.id)
        .order_by(PortfolioSnapshot.created_at)
    ]
    peak, worst = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def take_snapshots(db: Session, quotes: QuoteBook, now_ms: int) -> int:
    portfolios = db.query(Portfolio).join(Season).filter(Season.status == "active").all()
    for portfolio in portfolios:
        db.add(
            PortfolioSnapshot(
                portfolio_id=portfolio.id,
                value=portfolio_value(portfolio, quotes, now_ms, allow_stale=True),
                created_at=now_ms,
            )
        )
    db.flush()
    return len(portfolios)


def _leaders(scores: dict[int, float], best) -> list[int]:
    if not scores:
        return []
    target = best(scores.values())
    return [player_id for player_id, score in scores.items() if score == target]


def award_season_badges(db: Session, season: Season, quotes: QuoteBook, now_ms: int) -> list[Badge]:
    """Prize badges go only to accounts older than N days with enough trades (anti-abuse)."""
    rows = standings(db, season, quotes, now_ms)
    min_created_at = now_ms - PRIZE_MIN_ACCOUNT_AGE_DAYS * DAY_MS
    portfolios = {portfolio.id: portfolio for portfolio in db.query(Portfolio).filter_by(season_id=season.id)}

    eligible = [
        row
        for row in rows
        if row.qualified
        and not row.is_ai
        and portfolios[row.portfolio_id].player.created_at <= min_created_at
        and not portfolios[row.portfolio_id].player.is_banned
    ]
    rates = {}
    for row in eligible:
        rate = win_rate(db, portfolios[row.portfolio_id])
        if rate is not None:
            rates[row.player_id] = rate
    drawdowns = {row.player_id: max_drawdown(db, portfolios[row.portfolio_id]) for row in eligible}

    awarded = [(player_id, "sniper") for player_id in _leaders(rates, max)]
    awarded += [(player_id, "iron_nerves") for player_id in _leaders(drawdowns, min)]
    ai_returns = [row.return_pct for row in rows if row.is_ai]
    if ai_returns:
        best_ai = max(ai_returns)
        awarded += [(row.player_id, "beat_ai") for row in eligible if row.return_pct > best_ai]

    badges = [
        Badge(player_id=player_id, code=code, season_id=season.id, created_at=now_ms)
        for player_id, code in awarded
    ]
    db.add_all(badges)
    db.flush()
    return badges
