from app.core.config import settings
from app.game.config import DAY_MS, HOUR_MS
from tests.api.conftest import ALICE, auth
from tests.game.conftest import NOW

SAT = NOW - 12 * HOUR_MS + 3 * DAY_MS


def test_weekend_flow(client, db, clock, quotes, monkeypatch):
    from app.game.models import Player
    from app.game.quotes import Quote
    from app.game.weekend import register

    monkeypatch.setattr(settings, "BOT_USERNAME", "veydranox_bot")
    me = client.get("/game/me", headers=auth()).json()
    assert me["weekend"] == {"starts_at": SAT, "ends_at": SAT + 2 * DAY_MS, "joined": False,
                             "link": "https://t.me/veydranox_bot?start=weekend"}
    assert "weekend" not in me["portfolios"]

    alice = db.query(Player).filter_by(telegram_id=ALICE["id"]).one()
    register(db, alice, NOW)
    db.commit()
    me = client.get("/game/me", headers=auth()).json()
    assert me["weekend"]["joined"] is True and "weekend" not in me["portfolios"]
    order = {"season": "weekend", "symbol": "BTC/USDT", "side": "long", "amount_usdt": 1000}
    response = client.post("/game/orders", json=order, headers=auth())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "weekend_not_running"

    clock["now"] = SAT + HOUR_MS
    quotes.update(Quote("BTC/USDT", bid=99.0, ask=101.0, ts=clock["now"]))
    assert client.get("/game/me", headers=auth()).json()["portfolios"]["weekend"]["cash"] == 10_000
    assert client.post("/game/orders", json=order, headers=auth()).status_code == 200
    assert len(client.get("/game/positions?season=weekend", headers=auth()).json()) == 1
    board = client.get("/game/leaderboard?season=weekend", headers=auth()).json()
    assert board["scope"] == "global" and [row["nickname"] for row in board["rows"]] == ["alice"]
    assert client.get("/game/ai?season=weekend", headers=auth()).status_code == 200
