from dataclasses import replace

import pytest

from app.game.ai_personas import (
    PERSONAS,
    Signal,
    decide,
    ensure_ai_players,
    order_size,
    stop_prices,
    view,
)
from app.game.models import Player, Position
from app.game.seasons import join_season
from tests.game.conftest import NOW, make_season

BY_KEY = {persona.key: persona for persona in PERSONAS}
UPTREND = dict(ema_fast=101.0, ema_slow=100.0)
DOWNTREND = dict(ema_fast=99.0, ema_slow=100.0)


def signal(probability_up, **trend):
    trend = trend or UPTREND
    return Signal(candle_ts=NOW, probability_up=probability_up, **trend)


def test_personas_match_spec():
    lstm, rf, lr = BY_KEY["lstm"], BY_KEY["random_forest"], BY_KEY["logistic_regression"]
    assert (lstm.buy_threshold, lstm.sell_threshold, lstm.position_fraction) == (0.55, 0.45, 0.40)
    assert (lstm.stop_loss_pct, lstm.take_profit_pct, lstm.use_trend_filter) == (0.03, 0.06, True)
    assert (rf.buy_threshold, rf.sell_threshold, rf.position_fraction) == (0.65, 0.35, 0.15)
    assert (rf.stop_loss_pct, rf.take_profit_pct, rf.use_trend_filter) == (0.015, 0.03, True)
    assert (lr.buy_threshold, lr.sell_threshold, lr.position_fraction) == (0.55, 0.45, 0.25)
    assert lr.use_trend_filter is False


def test_view_thresholds_inclusive():
    lstm = BY_KEY["lstm"]
    assert view(lstm, signal(0.55)) == "bullish"
    assert view(lstm, signal(0.5499)) == "neutral"
    assert view(lstm, signal(0.45, **DOWNTREND)) == "bearish"
    assert view(lstm, signal(0.4501, **DOWNTREND)) == "neutral"


def test_trend_filter_blocks_counter_trend():
    assert view(BY_KEY["random_forest"], signal(0.7, **DOWNTREND)) == "neutral"
    assert view(BY_KEY["random_forest"], signal(0.3, **UPTREND)) == "neutral"
    assert view(BY_KEY["random_forest"], signal(0.7, ema_fast=None, ema_slow=None)) == "neutral"
    assert view(BY_KEY["logistic_regression"], signal(0.7, **DOWNTREND)) == "bullish"


@pytest.mark.parametrize(
    "stance, open_side, action",
    [
        ("bullish", None, "open_long"),
        ("bullish", "long", "hold"),
        ("bullish", "short", "close"),
        ("bearish", None, "open_short"),
        ("bearish", "short", "hold"),
        ("bearish", "long", "close"),
        ("neutral", "long", "hold"),
        ("neutral", None, "hold"),
    ],
)
def test_decide_matrix(stance, open_side, action):
    assert decide(stance, open_side) == action


def test_order_size_caps_by_cash_and_pair_limit(db, quotes):
    players = ensure_ai_players(db, NOW)
    portfolio = join_season(db, players["lstm"], make_season(db), NOW)
    assert order_size(BY_KEY["lstm"], portfolio, quotes, NOW) == pytest.approx(4000.0)

    portfolio.cash = 1000.0
    # Value 1000 → 40% is 400, below what cash allows.
    assert order_size(BY_KEY["lstm"], portfolio, quotes, NOW) == pytest.approx(400.0)

    # Cash 1000 + long 50 BTC at bid 99 → value 5950; only cash/(1+fee) is spendable.
    portfolio.positions.append(
        Position(symbol="BTC/USDT", side="long", qty=50.0, entry_price=100.0, reserved=5000.0, opened_at=NOW)
    )
    assert order_size(BY_KEY["lstm"], portfolio, quotes, NOW) == pytest.approx(1000.0 / 1.001)
    portfolio.positions.clear()

    lstm_greedy = replace(BY_KEY["lstm"], position_fraction=0.9)
    portfolio.cash = 10_000.0
    assert order_size(lstm_greedy, portfolio, quotes, NOW) == pytest.approx(5000.0)


def test_stop_prices_long_and_short():
    rf = BY_KEY["random_forest"]
    assert stop_prices(rf, "long", bid=99.0, ask=100.0) == pytest.approx((98.5, 103.0))
    assert stop_prices(rf, "short", bid=100.0, ask=101.0) == pytest.approx((101.5, 97.0))


def test_ensure_ai_players_idempotent(db):
    first = ensure_ai_players(db, NOW)
    second = ensure_ai_players(db, NOW)

    assert set(first) == {"lstm", "random_forest", "logistic_regression"}
    assert {p.id for p in first.values()} == {p.id for p in second.values()}
    assert db.query(Player).filter_by(is_ai=True).count() == 3
    assert all(p.telegram_id is None for p in first.values())
