from app.core.config import settings
from tests.api.conftest import ALICE, BOB, auth


def test_duel_flow(client, db, monkeypatch):
    from app.game.duels import accept_duel
    from app.game.models import Player

    monkeypatch.setattr(settings, "BOT_USERNAME", "veydranox_bot")
    assert client.get("/game/duel", headers=auth()).json() == {"state": "none"}

    body = client.post("/game/duel", headers=auth()).json()
    assert body["state"] == "open" and body["link"].endswith(f"?start=duel_{body['id']}")
    assert client.post("/game/duel", headers=auth()).json()["id"] == body["id"]
    assert "duel" not in client.get("/game/me", headers=auth()).json()["portfolios"]
    assert client.get("/game/positions?season=duel", headers=auth()).status_code == 404

    client.get("/game/me", headers=auth(BOB))
    bob = db.query(Player).filter_by(telegram_id=BOB["id"]).one()
    accept_duel(db, body["id"], bob, 1)
    db.commit()

    me = client.get("/game/me", headers=auth()).json()
    assert me["portfolios"]["duel"]["cash"] == 10_000
    order = {"season": "duel", "symbol": "BTC/USDT", "side": "long", "amount_usdt": 1000}
    assert client.post("/game/orders", json=order, headers=auth()).status_code == 200
    assert len(client.get("/game/positions?season=duel", headers=auth()).json()) == 1
    board = client.get("/game/leaderboard?season=duel", headers=auth(BOB)).json()
    assert [row["nickname"] for row in board["rows"]] and len(board["rows"]) == 2
    view = client.get("/game/duel", headers=auth(BOB)).json()
    assert view["state"] == "active" and view["rival"] == "alice"


def test_duel_cancel(client):
    client.post("/game/duel", headers=auth(ALICE))
    assert client.delete("/game/duel", headers=auth(ALICE)).json() == {"state": "none"}
