from app.game.config import SeasonKind
from app.game.jobs import run_seasons, run_snapshots, run_stops
from app.game.models import PortfolioSnapshot, Season
from app.game.quotes import Quote
from app.game.seasons import join_season
from app.game.trading import open_position
from tests.game.conftest import NOW, make_player, make_season


def test_seasons_job_rolls_over(db, quotes):
    sprint = make_season(db, SeasonKind.SPRINT)
    make_season(db, SeasonKind.WEEK)

    assert run_seasons(db, quotes, NOW) == 0
    assert db.query(Season).count() == 2

    assert run_seasons(db, quotes, sprint.ends_at) == 1
    assert sprint.status == "finished"
    current = db.query(Season).filter_by(kind="sprint", status="active").one()
    assert current.starts_at == sprint.ends_at


def test_seasons_job_retries_closing_season(db, quotes):
    sprint = make_season(db, SeasonKind.SPRINT)
    portfolio = join_season(db, make_player(db, telegram_id=1), sprint, NOW)
    position = open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW)

    # No fresh price when the season ends: it waits in "closing".
    assert run_seasons(db, quotes, sprint.ends_at) == 0
    assert sprint.status == "closing"
    assert position.closed_at is None

    later = sprint.ends_at + 5_000
    quotes.update(Quote("BTC/USDT", bid=105.0, ask=106.0, ts=later))
    assert run_seasons(db, quotes, later) == 1
    assert sprint.status == "finished"
    assert (position.close_reason, position.exit_price) == ("season_end", 105.0)


def test_stops_job_closes_hit_stop(db, quotes):
    portfolio = join_season(db, make_player(db, telegram_id=1), make_season(db), NOW)
    position = open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW, stop_loss=95.0)
    assert run_stops(db, quotes, NOW) == 0
    quotes.update(Quote("BTC/USDT", bid=94.0, ask=96.0, ts=NOW + 1))
    assert run_stops(db, quotes, NOW + 1) == 1
    assert position.close_reason == "stop_loss"


def test_snapshots_job_counts_active_portfolios(db, quotes):
    join_season(db, make_player(db, telegram_id=1), make_season(db), NOW)
    assert run_snapshots(db, quotes, NOW) == 1
    assert db.query(PortfolioSnapshot).count() == 1
