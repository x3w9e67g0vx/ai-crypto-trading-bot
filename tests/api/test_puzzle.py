from app.game.config import XP_PER_PUZZLE
from tests.api.conftest import BOB, auth
from tests.game.test_puzzle import add_candles


def test_puzzle_null_without_history(client):
    assert client.get("/game/puzzle", headers=auth()).json() == {"puzzle": None}
    response = client.post("/game/puzzle", json={"choice": "long"}, headers=auth())
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "puzzle_not_found"


def test_puzzle_answer_flow(client, db):
    add_candles(db)
    db.commit()
    before = client.get("/game/puzzle", headers=auth()).json()["puzzle"]
    assert before["result"] is None and before["xp"] == XP_PER_PUZZLE

    body = client.post("/game/puzzle", json={"choice": "long"}, headers=auth()).json()
    assert body["xp_awarded"] == XP_PER_PUZZLE
    assert body["player"]["xp"] == XP_PER_PUZZLE
    assert body["puzzle"]["result"]["correct"] is True
    assert body["puzzle"]["candles"] == before["candles"]

    again = client.post("/game/puzzle", json={"choice": "short"}, headers=auth()).json()
    assert again["xp_awarded"] == 0 and again["puzzle"]["result"]["choice"] == "long"
    # Another player gets the same puzzle, still unanswered.
    assert client.get("/game/puzzle", headers=auth(BOB)).json()["puzzle"]["result"] is None


def test_puzzle_bad_choice_422(client):
    assert client.post("/game/puzzle", json={"choice": "moon"}, headers=auth()).status_code == 422
