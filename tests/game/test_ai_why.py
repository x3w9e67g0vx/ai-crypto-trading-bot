from app.game.config import AI_VISIBILITY_DELAY_MS
from app.game.insights import ai_entry_why
from app.game.models import AiDecision, Portfolio
from app.game.quotes import Quote
from app.game.trading import open_position
from tests.game.conftest import NOW, make_player, make_season
from tests.game.test_ai_trader import BEARISH, BULLISH, btc_positions, turn
from tests.game.test_insights import add_candles

LATER = NOW + AI_VISIBILITY_DELAY_MS


def test_why_long_follows_the_decision(db, quotes):
    add_candles(db)
    turn(db, quotes, {"lstm": BULLISH})
    position = btc_positions(db, "lstm")[0]

    why = ai_entry_why(db, make_player(db, telegram_id=1), position.id, LATER)

    assert why["nickname"] == "LSTM"
    assert (why["symbol"], why["side"]) == ("BTC/USDT", "long")
    assert why["probability_up"] == 0.8
    assert why["threshold"] == 0.65
    assert why["trend_filter"] is True
    assert why["trend"] == "up"
    assert why["rsi"] is not None
    assert why["stop_pct"] < 0 < why["take_pct"]
    codes = [step["code"] for step in why["steps"]]
    assert codes[:2] == ["signal", "trend"]
    assert codes[2] in ("rsi_overbought", "rsi_oversold", "rsi_neutral")
    assert codes[3:] == ["size", "stops"]
    assert [step["lesson_id"] for step in why["steps"]] == ["10", "06", "07", "03", "04"]


def test_why_short_uses_sell_threshold_and_no_filter(db, quotes):
    turn(db, quotes, {"logistic_regression": BEARISH})
    position = btc_positions(db, "logistic_regression")[0]

    why = ai_entry_why(db, make_player(db, telegram_id=1), position.id, LATER)

    assert why["side"] == "short"
    assert why["threshold"] == 0.35
    assert why["trend"] == "down"  # from the decision snapshot
    assert why["rsi"] is None  # no candles
    assert [step["code"] for step in why["steps"]] == ["signal", "no_trend_filter", "size", "stops"]


def test_why_uses_snapshot_not_current_persona(db, quotes):
    turn(db, quotes, {"lstm": BULLISH})
    position = btc_positions(db, "lstm")[0]
    db.query(AiDecision).update({"buy_threshold": 0.6})

    assert ai_entry_why(db, make_player(db, telegram_id=1), position.id, LATER)["threshold"] == 0.6


def test_why_falls_back_to_persona_for_old_decisions(db, quotes):
    turn(db, quotes, {"lstm": BULLISH})
    position = btc_positions(db, "lstm")[0]
    db.query(AiDecision).update({"buy_threshold": None, "trend_filter": None, "ema_fast": None, "ema_slow": None})

    why = ai_entry_why(db, make_player(db, telegram_id=1), position.id, LATER)

    assert (why["threshold"], why["trend_filter"], why["trend"]) == (0.65, True, None)


def test_why_hidden_until_free_viewer_sees_position(db, quotes):
    turn(db, quotes, {"lstm": BULLISH})
    position = btc_positions(db, "lstm")[0]
    free = make_player(db, telegram_id=1)
    pro = make_player(db, telegram_id=2, is_pro_until=NOW + 1)

    assert ai_entry_why(db, free, position.id, NOW) is None
    assert ai_entry_why(db, pro, position.id, NOW) is not None


def test_why_only_for_ai_positions(db, quotes):
    human = make_player(db, telegram_id=1)
    portfolio = Portfolio(player_id=human.id, season_id=make_season(db).id, cash=10_000.0, created_at=NOW)
    db.add(portfolio)
    db.flush()
    quotes.update(Quote("BTC/USDT", bid=99.0, ask=101.0, ts=NOW))
    position = open_position(db, portfolio, "BTC/USDT", "long", 100.0, quotes, NOW)

    assert ai_entry_why(db, human, position.id, LATER) is None
    assert ai_entry_why(db, human, 999_999, LATER) is None
