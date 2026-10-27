import pytest

from app.game.config import DAY_MS, SeasonKind
from app.game.leaderboard import award_season_badges, max_drawdown, standings, take_snapshots, win_rate
from app.game.models import PortfolioSnapshot, Position
from app.game.seasons import ensure_current_season, join_season
from tests.game.conftest import NOW, make_player


def make_portfolio(db, season, cash, trades, **player_kw):
    player_kw.setdefault("telegram_id", None if player_kw.get("is_ai") else make_portfolio.counter)
    make_portfolio.counter += 1
    portfolio = join_season(db, make_player(db, **player_kw), season, NOW)
    portfolio.cash = cash
    portfolio.trades_count = trades
    return portfolio


make_portfolio.counter = 1


def close_with_pnl(db, portfolio, pnl):
    db.add(
        Position(
            portfolio_id=portfolio.id, symbol="BTC/USDT", side="long", qty=1, entry_price=1,
            reserved=1, opened_at=NOW, closed_at=NOW, exit_price=1, pnl=pnl, close_reason="manual",
        )
    )
    db.flush()


@pytest.fixture
def season(db):
    return ensure_current_season(db, SeasonKind.SPRINT, NOW)


def test_unqualified_ranked_after_qualified(db, season, quotes):
    make_portfolio(db, season, 20_000.0, 2, nickname="lucky")
    make_portfolio(db, season, 10_500.0, 5, nickname="steady")
    make_portfolio(db, season, 9_000.0, 7, nickname="loser")
    rows = standings(db, season, quotes, NOW)
    assert [row.nickname for row in rows] == ["steady", "loser", "lucky"]
    assert [row.rank for row in rows] == [1, 2, None]
    assert rows[0].return_pct == pytest.approx(5.0)


def test_ai_not_ranked_but_listed(db, season, quotes):
    make_portfolio(db, season, 11_000.0, 5, nickname="human")
    make_portfolio(db, season, 12_000.0, 9, nickname="LSTM", is_ai=True, ai_key="lstm")
    rows = standings(db, season, quotes, NOW)
    assert [(row.nickname, row.rank, row.is_ai) for row in rows] == [("LSTM", None, True), ("human", 1, False)]


def test_win_rate(db, season):
    portfolio = make_portfolio(db, season, 10_000.0, 6)
    assert win_rate(db, portfolio) is None
    for pnl in (10, -5, 3, 0):
        close_with_pnl(db, portfolio, pnl)
    assert win_rate(db, portfolio) == pytest.approx(0.5)


def test_max_drawdown_from_snapshots(db, season, quotes):
    portfolio = make_portfolio(db, season, 10_000.0, 5)
    for i, value in enumerate((12_000.0, 9_000.0, 11_000.0)):
        db.add(PortfolioSnapshot(portfolio_id=portfolio.id, value=value, created_at=NOW + i))
    db.flush()
    assert max_drawdown(db, portfolio) == pytest.approx(0.25)
    assert take_snapshots(db, quotes, NOW + 10) == 1


def test_badges_skip_young_accounts(db, season, quotes):
    old = make_portfolio(db, season, 10_100.0, 5, nickname="old")
    young = make_portfolio(db, season, 10_100.0, 5, nickname="young", created_at=NOW - DAY_MS)
    for portfolio in (old, young):
        close_with_pnl(db, portfolio, 10)
    codes = {(badge.player_id, badge.code) for badge in award_season_badges(db, season, quotes, NOW)}
    assert (old.player_id, "sniper") in codes
    assert (old.player_id, "iron_nerves") in codes
    assert all(player_id != young.player_id for player_id, _ in codes)


def test_beat_ai_badge(db, season, quotes):
    winner = make_portfolio(db, season, 11_000.0, 5)
    loser = make_portfolio(db, season, 10_000.0, 5)
    make_portfolio(db, season, 10_500.0, 5, is_ai=True, ai_key="random_forest", nickname="RF")
    codes = {(badge.player_id, badge.code) for badge in award_season_badges(db, season, quotes, NOW)}
    assert (winner.player_id, "beat_ai") in codes
    assert (loser.player_id, "beat_ai") not in codes
