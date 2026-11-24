import app.game.llm_review as llm
from app.game.errors import LlmUnavailable
from app.game.models import Payment, Player
from app.game.shop import DAY_MS
from tests.api.conftest import ALICE, BOB, auth
from tests.game.conftest import NOW


def _alice(db):
    return db.query(Player).filter_by(telegram_id=ALICE["id"]).one()


def _make_pro(db):
    _alice(db).is_pro_until = NOW + DAY_MS
    db.commit()


def _closed_position(client):
    order = {"season": "week", "symbol": "BTC/USDT", "side": "long", "amount_usdt": 1000}
    position = client.post("/game/orders", json=order, headers=auth()).json()
    client.post(f"/game/positions/{position['id']}/close", headers=auth())
    return position["id"]


def test_me_lists_cosmetics_and_wardrobe(client):
    player = client.get("/game/me", headers=auth()).json()["player"]
    assert player["cosmetics"] == {"frame": None, "nick_color": None, "ai_skin": None}
    assert player["pro_until"] is None
    gold = next(item for item in player["wardrobe"] if item["code"] == "frame_gold")
    assert gold == {"code": "frame_gold", "slot": "frame", "stars": None, "available": False}


def test_equip_needs_pro_or_purchase(client, db):
    assert client.patch("/game/me", json={"frame": "frame_gold"}, headers=auth()).status_code == 409
    _make_pro(db)
    body = client.patch("/game/me", json={"frame": "frame_gold"}, headers=auth()).json()
    assert body["player"]["cosmetics"]["frame"] == "frame_gold"

    assert client.patch("/game/me", json={"nick_color": "color_violet"}, headers=auth()).status_code == 409
    db.add(Payment(player_id=_alice(db).id, item="color_violet", stars=75, charge_id="c1", created_at=NOW))
    db.commit()
    body = client.patch("/game/me", json={"nick_color": "color_violet"}, headers=auth()).json()
    assert body["player"]["cosmetics"] == {"frame": "frame_gold", "nick_color": "color_violet", "ai_skin": None}

    # Leaving a slot out keeps it; null takes it off.
    body = client.patch("/game/me", json={"frame": None}, headers=auth()).json()
    assert body["player"]["cosmetics"]["frame"] is None
    assert body["player"]["cosmetics"]["nick_color"] == "color_violet"


def test_leaderboard_shows_cosmetics(client, db):
    _closed_position(client)
    _make_pro(db)
    client.patch("/game/me", json={"nick_color": "color_mint"}, headers=auth())

    rows = client.get("/game/leaderboard?season=week", headers=auth()).json()["rows"]
    me = next(row for row in rows if row["is_me"])
    assert (me["frame"], me["nick_color"]) == (None, "color_mint")
    assert "ai_skin" not in me


def test_llm_review_is_pro_only_and_cached(client, db, monkeypatch):
    calls = []

    def fake_ask(review, language):
        calls.append((review["position_id"], language))
        return "Хороший вход по тренду."

    monkeypatch.setattr(llm, "_ask", fake_ask)
    position_id = _closed_position(client)
    url = f"/game/positions/{position_id}/review/llm"

    response = client.post(url, headers=auth())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pro_required"

    _make_pro(db)
    assert client.post(url, headers=auth()).json() == {"position_id": position_id, "text": "Хороший вход по тренду."}
    assert client.post(url, headers=auth()).status_code == 200
    assert calls == [(position_id, "ru")]  # second call served from the cache

    assert client.post(url, headers=auth(BOB)).status_code == 404  # not Bob's


def test_llm_review_unavailable_is_503(client, db, monkeypatch):
    def broken(review, language):
        raise LlmUnavailable()

    monkeypatch.setattr(llm, "_ask", broken)
    position_id = _closed_position(client)
    _make_pro(db)

    response = client.post(f"/game/positions/{position_id}/review/llm", headers=auth())
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "llm_unavailable"
