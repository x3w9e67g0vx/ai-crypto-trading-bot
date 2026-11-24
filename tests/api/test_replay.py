from app.game.config import REPLAY_CANDLES, XP_PER_REPLAY
from tests.api.conftest import auth
from tests.game.test_replay import add_candles


def test_replay_null_without_history(client):
    assert client.get("/game/replay", headers=auth()).json() == {"replay": None}


def test_replay_flow(client, db):
    add_candles(db)
    db.commit()
    replay = client.get("/game/replay", headers=auth()).json()["replay"]
    assert len(replay["candles"]) == REPLAY_CANDLES

    body = client.post("/game/replay/finish", headers=auth()).json()
    assert body["xp_awarded"] == XP_PER_REPLAY and body["player"]["xp"] == XP_PER_REPLAY
    assert client.post("/game/replay/finish", headers=auth()).json()["xp_awarded"] == 0
