from app.game.models import Portfolio, Position
from tests.api.conftest import auth


def test_quests_flow(client, db):
    body = client.get("/game/quests?season=week", headers=auth()).json()
    assert [q["code"] for q in body["quests"]] == ["stops", "take_profit", "discipline"]
    assert body["xp_awarded"] == 0

    portfolio = db.query(Portfolio).one()
    db.add(Position(portfolio_id=portfolio.id, symbol="BTC/USDT", side="long", qty=1, entry_price=100,
                    reserved=100, take_profit=110, opened_at=1, closed_at=2, exit_price=110, pnl=10,
                    close_reason="take_profit"))
    db.commit()
    body = client.get("/game/quests?season=week", headers=auth()).json()
    assert body["xp_awarded"] == 30 and body["player"]["xp"] == 30
    assert client.get("/game/quests?season=week", headers=auth()).json()["xp_awarded"] == 0


def test_quests_bad_season_422(client):
    assert client.get("/game/quests?season=year", headers=auth()).status_code == 422
