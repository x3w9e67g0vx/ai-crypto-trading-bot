import math

import pytest

from app.game.config import DAY_MS
from app.game.errors import (
    DailyTradeLimit,
    InvalidStops,
    PairLimitExceeded,
    PositionExists,
    SeasonClosed,
    StaleQuote,
    UnknownSymbol,
)
from app.game.models import Portfolio
from app.game.quotes import Quote
from app.game.trading import check_stops, close_position, open_position, portfolio_value
from tests.game.conftest import NOW, make_player, make_season


@pytest.fixture
def portfolio(db):
    player = make_player(db, telegram_id=1)
    season = make_season(db)
    portfolio = Portfolio(player_id=player.id, season_id=season.id, cash=10_000.0, created_at=NOW)
    db.add(portfolio)
    db.flush()
    return portfolio


def set_quote(quotes, bid, ask, ts=NOW, symbol="BTC/USDT"):
    quotes.update(Quote(symbol, bid=bid, ask=ask, ts=ts))


def test_open_long_charges_ask_plus_fee(db, portfolio, quotes):
    position = open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW)
    assert position.qty == pytest.approx(1000 / 101)
    assert position.entry_price == 101.0
    assert portfolio.cash == pytest.approx(10_000 - 1000 - 1)
    assert portfolio.trades_count == 1


def test_close_long_at_bid(db, portfolio, quotes):
    position = open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW)
    set_quote(quotes, bid=110.0, ask=111.0, ts=NOW + 1)
    close_position(db, position, quotes, NOW + 1)
    assert position.exit_price == 110.0
    assert position.close_reason == "manual"
    assert position.closed_at == NOW + 1
    assert position.pnl == pytest.approx(position.qty * 110 * 0.999 - 1001)
    assert portfolio.cash == pytest.approx(10_000 + position.pnl)


def test_open_short_reserves_and_profits_on_drop(db, portfolio, quotes):
    position = open_position(db, portfolio, "BTC/USDT", "short", 1000.0, quotes, NOW)
    assert position.entry_price == 99.0
    assert portfolio.cash == pytest.approx(8999.0)
    set_quote(quotes, bid=89.0, ask=90.0, ts=NOW + 1)
    assert portfolio_value(portfolio, quotes, NOW + 1) == pytest.approx(8999 + 1000 + 9 * position.qty)
    close_position(db, position, quotes, NOW + 1)
    qty = 1000 / 99
    assert position.pnl == pytest.approx(9 * qty - qty * 90 * 0.001 - 1)


def test_short_loss_beyond_reserve(db, portfolio, quotes):
    position = open_position(db, portfolio, "BTC/USDT", "short", 5000.0, quotes, NOW)
    set_quote(quotes, bid=299.0, ask=300.0, ts=NOW + 1)
    value = portfolio_value(portfolio, quotes, NOW + 1)
    assert math.isfinite(value)
    assert value < 0
    close_position(db, position, quotes, NOW + 1)
    assert portfolio.cash == pytest.approx(value - position.qty * 300 * 0.001)


def test_open_rejects_over_half_portfolio(db, portfolio, quotes):
    with pytest.raises(PairLimitExceeded):
        open_position(db, portfolio, "BTC/USDT", "long", 5001.0, quotes, NOW)
    assert portfolio.cash == 10_000.0
    assert portfolio.trades_count == 0
    open_position(db, portfolio, "BTC/USDT", "long", 5000.0, quotes, NOW)


def test_daily_limit_20_user_trades(db, portfolio, quotes):
    for _ in range(10):
        position = open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW)
        close_position(db, position, quotes, NOW)
    with pytest.raises(DailyTradeLimit):
        open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW)
    tomorrow = NOW + DAY_MS
    set_quote(quotes, bid=99.0, ask=101.0, ts=tomorrow)
    open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, tomorrow)


def test_auto_closes_bypass_daily_limit(db, portfolio, quotes):
    for _ in range(9):
        position = open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW)
        close_position(db, position, quotes, NOW)
    open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW, stop_loss=95.0)
    position = open_position(db, portfolio, "ETH/USDT", "long", 100.0, quotes, NOW)
    set_quote(quotes, bid=94.0, ask=96.0, ts=NOW + 1)
    assert len(check_stops(db, quotes, NOW + 1)) == 1
    with pytest.raises(DailyTradeLimit):
        close_position(db, position, quotes, NOW + 1)


def test_stop_loss_triggers_on_bid(db, portfolio, quotes):
    position = open_position(
        db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW, stop_loss=95.0, take_profit=120.0
    )
    set_quote(quotes, bid=96.0, ask=94.0 + 3, ts=NOW + 1)
    assert check_stops(db, quotes, NOW + 1) == []
    set_quote(quotes, bid=94.0, ask=96.0, ts=NOW + 2)
    assert check_stops(db, quotes, NOW + 2) == [position]
    assert position.close_reason == "stop_loss"
    assert position.exit_price == 94.0


def test_take_profit_short_triggers_on_ask(db, portfolio, quotes):
    position = open_position(
        db, portfolio, "BTC/USDT", "short", 1000.0, quotes, NOW, stop_loss=110.0, take_profit=90.0
    )
    set_quote(quotes, bid=88.0, ask=89.0, ts=NOW + 1)
    assert check_stops(db, quotes, NOW + 1) == [position]
    assert position.close_reason == "take_profit"
    assert position.exit_price == 89.0


def test_stops_skip_stale_quotes(db, portfolio, quotes):
    position = open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW, stop_loss=95.0)
    set_quote(quotes, bid=94.0, ask=96.0, ts=NOW + 1)
    assert check_stops(db, quotes, NOW + 31_002) == []
    assert position.closed_at is None
    set_quote(quotes, bid=93.0, ask=95.0, ts=NOW + 40_000)
    assert check_stops(db, quotes, NOW + 40_000) == [position]
    assert position.exit_price == 93.0


def test_trading_paused_when_stale(db, portfolio, quotes):
    with pytest.raises(StaleQuote):
        open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW + 30_001)


def test_invalid_stops_rejected(db, portfolio, quotes):
    with pytest.raises(InvalidStops):
        open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW, stop_loss=102.0)
    with pytest.raises(InvalidStops):
        open_position(db, portfolio, "BTC/USDT", "short", 100.0, quotes, NOW, take_profit=100.0)


def test_position_exists(db, portfolio, quotes):
    open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW)
    with pytest.raises(PositionExists):
        open_position(db, portfolio, "BTC/USDT", "short", 100.0, quotes, NOW)


def test_unknown_symbol(db, portfolio, quotes):
    with pytest.raises(UnknownSymbol):
        open_position(db, portfolio, "FOO/USDT", "long", 100.0, quotes, NOW)


def test_closed_season_rejects_orders(db, portfolio, quotes):
    portfolio.season.status = "finished"
    with pytest.raises(SeasonClosed):
        open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW)
