from datetime import UTC, datetime

import pytest

from app.game.config import DAY_MS, SeasonKind
from app.game.errors import SeasonClosed
from app.game.models import Season
from app.game.quotes import Quote
from app.game.seasons import ensure_current_season, finalize_season, join_season, season_bounds
from app.game.trading import open_position
from tests.game.conftest import NOW, make_player


def ms(*args):
    return int(datetime(*args, tzinfo=UTC).timestamp() * 1000)


def test_sprint_bounds_utc_day():
    assert season_bounds(SeasonKind.SPRINT, NOW) == (ms(2026, 10, 28), ms(2026, 10, 29))
    assert season_bounds(SeasonKind.SPRINT, ms(2026, 10, 28)) == (ms(2026, 10, 28), ms(2026, 10, 29))


def test_week_bounds_monday():
    assert season_bounds(SeasonKind.WEEK, NOW) == (ms(2026, 10, 26), ms(2026, 11, 2))
    assert season_bounds(SeasonKind.WEEK, ms(2026, 11, 2)) == (ms(2026, 11, 2), ms(2026, 11, 9))
    assert season_bounds(SeasonKind.WEEK, ms(2026, 11, 1, 23, 59)) == (ms(2026, 10, 26), ms(2026, 11, 2))


def test_ensure_current_season_idempotent(db):
    first = ensure_current_season(db, SeasonKind.WEEK, NOW)
    second = ensure_current_season(db, SeasonKind.WEEK, NOW + DAY_MS)
    assert first.id == second.id
    assert first.status == "active"
    sprint = ensure_current_season(db, SeasonKind.SPRINT, NOW)
    assert sprint.id != first.id
    assert db.query(Season).count() == 2


def test_join_is_idempotent_and_funds_10000(db):
    player = make_player(db, telegram_id=1)
    season = ensure_current_season(db, SeasonKind.SPRINT, NOW)
    portfolio = join_season(db, player, season, NOW)
    assert portfolio.cash == 10_000.0
    assert join_season(db, player, season, NOW + 1).id == portfolio.id


def test_banned_player_cannot_join(db):
    player = make_player(db, telegram_id=1, is_banned=True)
    season = ensure_current_season(db, SeasonKind.SPRINT, NOW)
    with pytest.raises(SeasonClosed):
        join_season(db, player, season, NOW)


def test_finalize_before_end_is_noop(db, quotes):
    season = ensure_current_season(db, SeasonKind.SPRINT, NOW)
    assert finalize_season(db, season, quotes, NOW) is False
    assert season.status == "active"


def test_finalize_closes_positions_at_market(db, quotes):
    season = ensure_current_season(db, SeasonKind.SPRINT, NOW)
    portfolio = join_season(db, make_player(db, telegram_id=1), season, NOW)
    position = open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW)
    end = season.ends_at
    quotes.update(Quote("BTC/USDT", bid=120.0, ask=121.0, ts=end))
    assert finalize_season(db, season, quotes, end) is True
    assert season.status == "finished"
    assert position.close_reason == "season_end"
    assert position.exit_price == 120.0


def test_finalize_waits_for_fresh_quotes(db, quotes):
    season = ensure_current_season(db, SeasonKind.SPRINT, NOW)
    portfolio = join_season(db, make_player(db, telegram_id=1), season, NOW)
    position = open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW)
    end = season.ends_at
    assert finalize_season(db, season, quotes, end) is False
    assert season.status == "closing"
    assert position.closed_at is None
    with pytest.raises(SeasonClosed):
        open_position(db, portfolio, "ETH/USDT", "long", 100.0, quotes, end)
    quotes.update(Quote("BTC/USDT", bid=98.0, ask=100.0, ts=end + 60_000))
    assert finalize_season(db, season, quotes, end + 60_000) is True
    assert position.exit_price == 98.0
    assert season.status == "finished"
