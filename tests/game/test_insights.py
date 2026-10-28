import pytest

from app.core.db.models import Candle
from app.game.config import AI_VISIBILITY_DELAY_MS
from app.game.insights import CANDLE_MS, Indicators, indicators_at, order_tips, trade_review
from app.game.models import AiDecision, Portfolio
from app.game.quotes import Quote
from app.game.trading import close_position, open_position
from tests.game.conftest import NOW, make_player, make_season

UP = Indicators(rsi=80.0, ema_fast=105.0, ema_slow=100.0, trend="up")
DOWN = Indicators(rsi=20.0, ema_fast=95.0, ema_slow=100.0, trend="down")
CALM = Indicators(rsi=50.0, ema_fast=105.0, ema_slow=100.0, trend="up")


def add_candles(db, *, rising=True, count=60, end_ms=NOW, symbol="BTC/USDT"):
    """`count` closed 5m candles, the last one closing at end_ms; mostly rising or falling."""
    first = end_ms - count * CANDLE_MS
    close = 100.0
    for i in range(count):
        step = 1.0 if i % 5 else -0.5
        close += step if rising else -step
        db.add(
            Candle(
                symbol=symbol, timeframe="5m", timestamp=first + i * CANDLE_MS,
                open=close, high=close + 1, low=close - 1, close=close, volume=1.0,
            )
        )
    db.flush()


@pytest.fixture
def player(db):
    return make_player(db, telegram_id=1)


@pytest.fixture
def portfolio(db, player):
    season = make_season(db)
    portfolio = Portfolio(player_id=player.id, season_id=season.id, cash=10_000.0, created_at=NOW)
    db.add(portfolio)
    db.flush()
    return portfolio


def test_indicators_from_closed_candles(db):
    add_candles(db, rising=True)
    up = indicators_at(db, "BTC/USDT", NOW)
    assert up.trend == "up" and up.rsi > 70
    add_candles(db, rising=False, symbol="ETH/USDT")
    down = indicators_at(db, "ETH/USDT", NOW)
    assert down.trend == "down" and down.rsi < 30


def test_indicators_none_without_fresh_candles(db):
    assert indicators_at(db, "BTC/USDT", NOW) is None
    add_candles(db, count=10)
    assert indicators_at(db, "BTC/USDT", NOW) is None  # too few
    add_candles(db, symbol="ETH/USDT", end_ms=NOW - 60 * 60 * 1000)
    assert indicators_at(db, "ETH/USDT", NOW) is None  # stale
    # A candle still forming at ts is not used.
    add_candles(db, symbol="SOL/USDT", end_ms=NOW + CANDLE_MS)
    assert indicators_at(db, "SOL/USDT", NOW) is not None


def codes(tips):
    return [tip["code"] for tip in tips]


def test_tip_rules(db, player, portfolio, quotes):
    long = open_position(db, portfolio, "BTC/USDT", "long", 4000.0, quotes, NOW)
    assert codes(order_tips(db, player, long, UP, 10_000.0, NOW)) == ["overbought_buy", "no_stop"]
    other = make_player(db, telegram_id=2, nickname="other")
    assert codes(order_tips(db, other, long, DOWN, 10_000.0, NOW)) == ["against_trend", "no_stop"]
    third = make_player(db, telegram_id=3, nickname="third")
    tips = order_tips(db, third, long, None, 10_000.0, NOW)
    assert tips == [{"code": "no_stop", "lesson_id": "04"}, {"code": "big_position", "lesson_id": "03"}]

    short = open_position(db, portfolio, "ETH/USDT", "short", 500.0, quotes, NOW, stop_loss=120.0)
    fourth = make_player(db, telegram_id=4, nickname="fourth")
    assert codes(order_tips(db, fourth, short, DOWN, 10_000.0, NOW)) == ["oversold_short"]
    assert order_tips(db, fourth, short, Indicators(50.0, 95.0, 100.0, "down"), 10_000.0, NOW + 1) == []


def test_tips_capped_and_once_per_day(db, player, portfolio, quotes):
    long = open_position(db, portfolio, "BTC/USDT", "long", 4000.0, quotes, NOW)
    assert len(order_tips(db, player, long, UP, 10_000.0, NOW)) == 2
    # The two shown today are skipped; the third rule comes through.
    assert codes(order_tips(db, player, long, UP, 10_000.0, NOW + 1)) == ["big_position"]
    assert order_tips(db, player, long, UP, 10_000.0, NOW + 2) == []
    assert codes(order_tips(db, player, long, UP, 10_000.0, NOW + 24 * 60 * 60 * 1000))[:1] == ["overbought_buy"]


def _closed_long(db, portfolio, quotes, *, bid, reason="manual", stop_loss=None, at=NOW + 10 * 60_000):
    position = open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW, stop_loss=stop_loss)
    quotes.update(Quote("BTC/USDT", bid=bid, ask=bid + 2, ts=at))
    close_position(db, position, quotes, at, reason=reason, is_user=reason == "manual")
    return position


def test_review_result_and_notes(db, player, portfolio, quotes):
    add_candles(db, rising=True, end_ms=NOW)
    position = _closed_long(db, portfolio, quotes, bid=90.0)
    review = trade_review(db, player, position, NOW + 3 * AI_VISIBILITY_DELAY_MS)
    assert review["symbol"] == "BTC/USDT" and review["side"] == "long"
    assert review["result"]["pnl"] == pytest.approx(position.pnl)
    assert review["result"]["pnl_pct"] == pytest.approx(position.pnl / position.reserved * 100)
    assert review["result"]["duration_ms"] == 10 * 60_000
    assert review["entry"]["trend"] == "up"
    assert {"entry_overbought", "with_trend", "no_stop_loss"} <= set(review["notes"])

    stopped = _closed_long(
        db, portfolio, quotes, bid=75.0, reason="stop_loss", stop_loss=80.0, at=NOW + 20 * 60_000
    )
    notes = trade_review(db, player, stopped, NOW + 3 * AI_VISIBILITY_DELAY_MS)["notes"]
    assert "stopped_out" in notes and "no_stop_loss" not in notes


def _ai(db, key, view, created_at, symbol="BTC/USDT"):
    ai = make_player(db, nickname=key, is_ai=True, ai_key=key)
    db.add(AiDecision(player_id=ai.id, symbol=symbol, candle_ts=created_at - CANDLE_MS,
                      probability_up=0.7 if view == "bullish" else 0.3, view=view, created_at=created_at))
    db.flush()
    return ai


def test_review_ai_opinions_at_entry(db, player, portfolio, quotes):
    _ai(db, "lstm", "bullish", NOW - 60_000)
    _ai(db, "random_forest", "bearish", NOW - 2 * 60_000)
    late = _ai(db, "logistic_regression", "bullish", NOW - 3 * 60_000)
    # A newer opinion after the entry is not what the AI thought at entry.
    db.add(AiDecision(player_id=late.id, symbol="BTC/USDT", candle_ts=NOW, probability_up=0.1,
                      view="bearish", created_at=NOW + 60_000))
    db.flush()
    position = _closed_long(db, portfolio, quotes, bid=110.0)
    review = trade_review(db, player, position, NOW + 3 * AI_VISIBILITY_DELAY_MS)
    views = {row["nickname"]: row["view"] for row in review["ai"]}
    assert views == {"lstm": "bullish", "random_forest": "bearish", "logistic_regression": "bullish"}
    assert "with_ai" in review["notes"]


def test_review_hides_fresh_ai_opinions_for_free(db, player, portfolio, quotes):
    _ai(db, "lstm", "bullish", NOW - 60_000)
    position = _closed_long(db, portfolio, quotes, bid=110.0)
    assert trade_review(db, player, position, NOW + 30 * 60_000)["ai"] == []
    player.is_pro_until = NOW + 10 * AI_VISIBILITY_DELAY_MS
    assert len(trade_review(db, player, position, NOW + 30 * 60_000)["ai"]) == 1


def test_review_without_candles(db, player, portfolio, quotes):
    position = _closed_long(db, portfolio, quotes, bid=110.0)
    review = trade_review(db, player, position, NOW + 3 * AI_VISIBILITY_DELAY_MS)
    assert review["entry"] is None and review["exit"] is None
    assert review["notes"] == []
