from app.core.db.models import Indicator
from app.game.ai_personas import Signal
from app.game.candles import store_candle
from app.game.config import CANDLE_TIMEFRAME_MS, SeasonKind
from app.game.jobs import AiJob, run_seasons, run_snapshots, run_stops
from app.game.models import AiDecision, PortfolioSnapshot, Season
from app.game.price_feed import ClosedCandle
from app.game.quotes import Quote
from app.game.seasons import join_season
from app.game.trading import open_position
from tests.game.conftest import NOW, make_player, make_season

# A candle that closed 30 s before NOW.
FRESH = NOW - CANDLE_TIMEFRAME_MS - 30_000


class FakeLoader:
    def __init__(self, empty=False):
        self.calls = []
        self.empty = empty

    def __call__(self, db, symbol, candle_ts):
        self.calls.append((symbol, candle_ts))
        if self.empty:
            return {}
        return {"lstm": Signal(candle_ts=candle_ts, probability_up=0.7, ema_fast=101.0, ema_slow=100.0)}


def add_candle(db, ts, source="binance"):
    store_candle(db, ClosedCandle("BTC/USDT", ts, 100.0, 101.0, 99.0, 100.0, 1.0), source=source)


def test_ai_job_trades_fresh_candle(db, quotes):
    add_candle(db, FRESH)
    loader = FakeLoader()
    assert AiJob(signals_loader=loader).run(db, quotes, NOW) == 1
    assert loader.calls == [("BTC/USDT", FRESH)]
    assert db.query(Indicator).count() == 1
    assert db.query(AiDecision).filter_by(symbol="BTC/USDT", candle_ts=FRESH).count() == 1


def test_ai_job_skips_old_candle(db, quotes):
    add_candle(db, NOW - CANDLE_TIMEFRAME_MS - 3 * 60_000)
    loader = FakeLoader()
    assert AiJob(signals_loader=loader).run(db, quotes, NOW) == 0
    assert loader.calls == []


def test_ai_job_once_per_candle(db, quotes):
    add_candle(db, FRESH)
    loader = FakeLoader()
    job = AiJob(signals_loader=loader)
    job.run(db, quotes, NOW)
    assert job.run(db, quotes, NOW + 10_000) == 0
    assert len(loader.calls) == 1

    # A restarted process sees the stored decision and does not trade again.
    other = FakeLoader()
    assert AiJob(signals_loader=other).run(db, quotes, NOW + 20_000) == 0
    assert other.calls == []


def test_ai_job_skips_bybit_candle(db, quotes):
    add_candle(db, FRESH, source="bybit")
    loader = FakeLoader()
    assert AiJob(signals_loader=loader).run(db, quotes, NOW) == 0
    assert loader.calls == []


def test_ai_job_remembers_empty_signals(db, quotes):
    add_candle(db, FRESH)
    loader = FakeLoader(empty=True)
    job = AiJob(signals_loader=loader)
    assert job.run(db, quotes, NOW) == 0
    assert job.run(db, quotes, NOW + 10_000) == 0
    assert len(loader.calls) == 1
    assert job.tried == {"BTC/USDT": FRESH}


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
