from app.game.config import CANDLE_TIMEFRAME_MS, XP_PER_GUESS_HIT
from tests.api.conftest import auth
from tests.game.conftest import NOW
from tests.game.test_guesses import add_ai_views, add_candle


def test_guess_flow(client, db, clock):
    body = client.get("/game/guess", params={"symbol": "BTC/USDT"}, headers=auth()).json()
    assert body["guess"]["current"] is None and body["guess"]["candle_ts"] == NOW + CANDLE_TIMEFRAME_MS

    payload = {"symbol": "BTC/USDT", "price": "up", "view": "bullish"}
    body = client.post("/game/guess", json=payload, headers=auth()).json()
    assert body["guess"]["current"]["price"] == "up"
    assert client.post("/game/guess", json=payload, headers=auth()).status_code == 409

    add_candle(db, NOW + CANDLE_TIMEFRAME_MS, 100.0, 101.0)
    add_ai_views(db, NOW + CANDLE_TIMEFRAME_MS, "bullish")
    db.commit()
    clock["now"] = NOW + 2 * CANDLE_TIMEFRAME_MS
    body = client.get("/game/guess", params={"symbol": "BTC/USDT"}, headers=auth()).json()
    assert body["guess"]["xp_awarded"] == 2 * XP_PER_GUESS_HIT
    assert body["guess"]["recent"][0]["xp"] == 2 * XP_PER_GUESS_HIT


def test_guess_validation(client):
    assert client.post("/game/guess", json={"symbol": "BTC/USDT", "price": "moon", "view": "bullish"},
                       headers=auth()).status_code == 422
    assert client.get("/game/guess", params={"symbol": "DOGE/USDT"}, headers=auth()).status_code in (400, 409)
