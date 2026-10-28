from app.game.ai_personas import ensure_ai_players
from app.game.models import Player, Portfolio
from tests.api.conftest import ALICE, BOB, auth, sign_init_data
from tests.game.conftest import NOW


def test_invalid_init_data_rejected(client, db):
    forged = sign_init_data(ALICE, token="999:other-bot")
    expired = sign_init_data(ALICE, auth_date=1)

    for headers in ({}, {"Authorization": f"tma {forged}"}, {"Authorization": f"tma {expired}"}):
        response = client.get("/game/me", headers=headers)
        assert response.status_code == 401

    assert db.query(Player).count() == 0


def test_first_visit_creates_player_and_joins_both_seasons(client, db):
    response = client.get("/game/me", headers=auth(ALICE))

    assert response.status_code == 200
    body = response.json()
    assert body["player"]["nickname"] == "alice"
    assert body["player"]["language"] == "ru"
    assert body["player"]["league_tier"] == "bronze"
    assert body["player"]["needs_nickname"] is True
    assert body["player"]["is_pro"] is False
    for kind in ("sprint", "week"):
        portfolio = body["portfolios"][kind]
        assert portfolio["cash"] == 10_000
        assert portfolio["value"] == 10_000
        assert portfolio["return_pct"] == 0
        assert portfolio["trades_today"] == 0
        assert portfolio["trades_limit"] == 20
        assert portfolio["starts_at"] <= NOW < portfolio["ends_at"]

    bob = client.get("/game/me", headers=auth(BOB)).json()
    assert bob["player"]["nickname"] == "Bob"
    assert bob["player"]["language"] == "en"


def test_me_is_idempotent(client, db):
    first = client.get("/game/me", headers=auth()).json()
    second = client.get("/game/me", headers=auth()).json()

    assert first["player"]["id"] == second["player"]["id"]
    assert db.query(Player).count() == 1
    assert db.query(Portfolio).count() == 2


def test_set_nickname_clears_needs_nickname(client):
    client.get("/game/me", headers=auth())

    response = client.patch("/game/me", json={"nickname": "Трейдер_1"}, headers=auth())

    assert response.status_code == 200
    assert response.json()["player"]["nickname"] == "Трейдер_1"
    assert response.json()["player"]["needs_nickname"] is False
    assert client.get("/game/me", headers=auth()).json()["player"]["needs_nickname"] is False


def test_nickname_taken_case_insensitive_including_ai(client, db):
    ensure_ai_players(db, NOW)
    db.commit()
    client.get("/game/me", headers=auth(BOB))
    client.patch("/game/me", json={"nickname": "Bobby"}, headers=auth(BOB))

    for taken in ("bobby", "lstm"):
        response = client.patch("/game/me", json={"nickname": taken}, headers=auth(ALICE))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "nickname_taken"

    # Keeping your own nickname in a different case is fine.
    assert client.patch("/game/me", json={"nickname": "BOBBY"}, headers=auth(BOB)).status_code == 200


def test_invalid_nickname(client):
    for bad in ("ab", "x" * 17, "bad name", "<script>"):
        response = client.patch("/game/me", json={"nickname": bad}, headers=auth())
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "invalid_nickname"


def test_language_switch(client):
    response = client.patch("/game/me", json={"language": "en"}, headers=auth())
    assert response.json()["player"]["language"] == "en"

    assert client.patch("/game/me", json={"language": "de"}, headers=auth()).status_code == 422


def test_banned_player_forbidden(client, db):
    client.get("/game/me", headers=auth())
    db.query(Player).filter_by(telegram_id=ALICE["id"]).update({"is_banned": True})
    db.commit()

    response = client.get("/game/me", headers=auth())

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "banned"


def test_first_visit_logs_start_and_return(client, db, clock):
    from app.game.models import Event

    client.get("/game/me", headers=auth(ALICE))
    client.get("/game/me", headers=auth(ALICE))
    assert sorted(kind for (kind,) in db.query(Event.kind)) == ["return", "start"]

    clock["now"] = NOW + 24 * 60 * 60 * 1000
    client.get("/game/me", headers=auth(ALICE))
    assert sorted(kind for (kind,) in db.query(Event.kind)) == ["return", "return", "start"]
