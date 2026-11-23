import pytest

from app.game.channel import day_key
from app.game.config import HOUR_MS, XP_PER_PUZZLE
from app.game.insights import CANDLE_MS, indicators_at
from app.game.models import DailyPuzzle
from app.game.puzzle import setup_answer
from tests.api.conftest import auth
from tests.game.conftest import NOW
from tests.game.test_insights import add_candles

PUZZLE_TS = NOW - NOW % (24 * HOUR_MS) - 3 * HOUR_MS


@pytest.fixture
def puzzle(session_factory):
    db = session_factory()
    add_candles(db, count=200, end_ms=PUZZLE_TS + 12 * CANDLE_MS)
    indicators = indicators_at(db, "BTC/USDT", PUZZLE_TS)
    answer = setup_answer(indicators)
    db.add(DailyPuzzle(
        day=day_key(NOW), symbol="BTC/USDT", ts=PUZZLE_TS, answer=answer, rsi=indicators.rsi,
        ema_fast=indicators.ema_fast, ema_slow=indicators.ema_slow, created_at=NOW,
    ))
    db.commit()
    db.close()
    return answer


def test_puzzle_null_without_candles(client):
    response = client.get("/game/puzzle", headers=auth())
    assert response.status_code == 200
    assert response.json() is None


def test_puzzle_hides_answer_until_answered(client, puzzle):
    body = client.get("/game/puzzle", headers=auth()).json()
    assert "answer" not in body
    assert body["answered"] is None
    assert body["symbol"] == "BTC/USDT"
    assert len(body["candles"]) == 60
    assert len(body["ema_fast"]) == len(body["ema_slow"]) == 60
    response = client.post("/game/puzzle/answer", json={"choice": puzzle}, headers=auth())
    assert response.status_code == 200
    assert response.json()["result"]["correct"] is True
    assert response.json()["player"]["xp"] == XP_PER_PUZZLE
    body = client.get("/game/puzzle", headers=auth()).json()
    assert body["answered"]["answer"] == puzzle
    assert len(body["answered"]["after"]) == 12


def test_answer_twice_conflict(client, puzzle):
    client.post("/game/puzzle/answer", json={"choice": puzzle}, headers=auth())
    response = client.post("/game/puzzle/answer", json={"choice": puzzle}, headers=auth())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "puzzle_answered"
    assert client.get("/game/me", headers=auth()).json()["player"]["xp"] == XP_PER_PUZZLE


def test_answer_bad_choice_422(client, puzzle):
    response = client.post("/game/puzzle/answer", json={"choice": "buy"}, headers=auth())
    assert response.status_code == 422


def test_answer_without_puzzle_404(client):
    response = client.post("/game/puzzle/answer", json={"choice": "long"}, headers=auth())
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "puzzle_not_found"
