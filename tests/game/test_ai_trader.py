import pytest

from app.game.ai_personas import Signal, ensure_ai_players
from app.game.ai_trader import run_ai_turn
from app.game.config import SeasonKind
from app.game.errors import UnknownSymbol
from app.game.models import AiDecision, Fill, LeagueMembership, Player, Portfolio
from app.game.quotes import Quote
from app.game.seasons import ensure_current_season, join_season
from app.game.trading import open_positions
from tests.game.conftest import NOW

BAR_MS = 5 * 60 * 1000
CANDLE = NOW - BAR_MS
BULLISH = dict(probability_up=0.7, ema_fast=101.0, ema_slow=100.0)
BEARISH = dict(probability_up=0.3, ema_fast=99.0, ema_slow=100.0)


def turn(db, quotes, signals, *, bars_later=0, symbol="BTC/USDT"):
    now = NOW + bars_later * BAR_MS
    quotes.update(Quote(symbol, bid=99.0, ask=101.0, ts=now))
    candle = CANDLE + bars_later * BAR_MS
    return run_ai_turn(
        db,
        symbol,
        candle,
        {key: Signal(candle_ts=candle, **values) for key, values in signals.items()},
        quotes,
        now,
    )


def portfolios_of(db, ai_key):
    return (
        db.query(Portfolio)
        .join(Player)
        .filter(Player.ai_key == ai_key)
        .order_by(Portfolio.season_id)
        .all()
    )


def btc_positions(db, ai_key):
    return [p for portfolio in portfolios_of(db, ai_key) for p in open_positions(portfolio) if p.symbol == "BTC/USDT"]


def test_bullish_opens_long_in_both_seasons(db, quotes):
    decisions = turn(db, quotes, {"lstm": BULLISH})

    assert [(d.view, d.candle_ts, d.probability_up) for d in decisions] == [("bullish", CANDLE, 0.7)]
    kinds = {portfolio.season.kind for portfolio in portfolios_of(db, "lstm")}
    assert kinds == {SeasonKind.SPRINT.value, SeasonKind.WEEK.value}
    positions = btc_positions(db, "lstm")
    assert len(positions) == 2
    for position in positions:
        assert position.side == "long"
        assert position.reserved == pytest.approx(4000.0)
        assert position.stop_loss == pytest.approx(101.0 * 0.97)
        assert position.take_profit == pytest.approx(101.0 * 1.06)


def test_bearish_closes_long_then_opens_short_next_candle(db, quotes):
    turn(db, quotes, {"lstm": BULLISH})
    turn(db, quotes, {"lstm": BEARISH}, bars_later=1)
    assert btc_positions(db, "lstm") == []

    turn(db, quotes, {"lstm": BEARISH}, bars_later=2)
    assert [p.side for p in btc_positions(db, "lstm")] == ["short", "short"]


def test_run_ai_turn_idempotent(db, quotes):
    turn(db, quotes, {"lstm": BULLISH})
    assert turn(db, quotes, {"lstm": BULLISH}) == []

    assert db.query(AiDecision).count() == 1
    assert db.query(Fill).count() == 2
    assert len(btc_positions(db, "lstm")) == 2


def test_signal_for_other_candle_ignored(db, quotes):
    stale = {"lstm": Signal(candle_ts=CANDLE - BAR_MS, **BULLISH)}
    assert run_ai_turn(db, "BTC/USDT", CANDLE, stale, quotes, NOW) == []
    assert db.query(AiDecision).count() == 0
    assert db.query(Fill).count() == 0


def test_rejected_order_does_not_abort_turn(db, quotes):
    # LSTM's week portfolio has used up today's 20 trades.
    lstm = ensure_ai_players(db, NOW)["lstm"]
    week = join_season(db, lstm, ensure_current_season(db, SeasonKind.WEEK, NOW), NOW)
    for _ in range(20):
        db.add(Fill(portfolio_id=week.id, position_id=0, symbol="ETH/USDT", side="buy",
                    qty=1.0, price=1.0, fee=0.0, is_user=True, created_at=NOW))
    db.flush()

    decisions = turn(db, quotes, {"lstm": BULLISH, "random_forest": BULLISH})

    assert [d.view for d in decisions] == ["bullish", "bullish"]
    assert {p.portfolio.season.kind for p in btc_positions(db, "lstm")} == {SeasonKind.SPRINT.value}
    assert len(btc_positions(db, "random_forest")) == 2


def test_ai_not_in_league_groups(db, quotes):
    turn(db, quotes, {"lstm": BULLISH, "random_forest": BULLISH, "logistic_regression": BULLISH})
    assert db.query(LeagueMembership).count() == 0


def test_unknown_symbol_rejected(db, quotes):
    with pytest.raises(UnknownSymbol):
        run_ai_turn(db, "BNB/USDT", CANDLE, {}, quotes, NOW)
