from app.game.config import LEVEL_XP, XP_PER_LESSON
from app.game.lessons import get_lesson
from app.game.models import Player
from app.game.models import Player
from app.game.quotes import Quote
from tests.api.conftest import ALICE, BOB, auth
from tests.game.conftest import NOW


def test_lessons_list_in_player_language(client):
    ru = client.get("/game/lessons", headers=auth(ALICE)).json()
    en = client.get("/game/lessons", headers=auth(BOB)).json()
    assert [row["id"] for row in ru] == [f"{n:02d}" for n in range(1, 11)]
    assert ru[0]["title"] == get_lesson("ru", "01").title
    assert en[0]["title"] == get_lesson("en", "01").title
    assert ru[0] == {"id": "01", "title": ru[0]["title"], "done": False, "xp": XP_PER_LESSON}


def test_lesson_detail_hides_answer(client):
    body = client.get("/game/lessons/07", headers=auth()).json()
    lesson = get_lesson("ru", "07")
    assert body["title"] == lesson.title
    assert body["blocks"] == [dict(block) for block in lesson.blocks]
    assert body["question"] == lesson.question
    assert body["options"] == list(lesson.options)
    assert "answer" not in body


def test_complete_lesson_api_idempotent(client):
    answer = get_lesson("ru", "01").answer
    first = client.post("/game/lessons/01/complete", json={"answer": answer}, headers=auth())
    assert first.status_code == 200
    assert first.json()["xp_awarded"] == XP_PER_LESSON
    assert first.json()["player"]["xp"] == XP_PER_LESSON
    again = client.post("/game/lessons/01/complete", json={"answer": answer}, headers=auth())
    assert again.json()["xp_awarded"] == 0
    assert again.json()["player"]["xp"] == XP_PER_LESSON
    assert client.get("/game/lessons", headers=auth()).json()[0]["done"] is True


def test_wrong_answer_rejected(client):
    lesson = get_lesson("ru", "01")
    response = client.post(
        "/game/lessons/01/complete", json={"answer": (lesson.answer + 1) % len(lesson.options)}, headers=auth()
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "wrong_answer"


def test_unknown_lesson_404(client):
    assert client.get("/game/lessons/99", headers=auth()).status_code == 404
    assert client.post("/game/lessons/99/complete", json={"answer": 0}, headers=auth()).status_code == 404


def test_me_has_level(client):
    player = client.get("/game/me", headers=auth()).json()["player"]
    assert player["level"] == 1
    assert player["level_xp"] == 0
    assert player["next_level_xp"] == LEVEL_XP[1]
    assert player["next_unlocks"] == ["BNB/USDT", "XRP/USDT"]


def test_level_unlocks_trading_pair(client, db, quotes):
    client.get("/game/me", headers=auth())
    db.query(Player).filter_by(telegram_id=ALICE["id"]).one().xp = LEVEL_XP[1]
    db.commit()
    quotes.update(Quote("BNB/USDT", bid=99.0, ask=101.0, ts=NOW))
    assert "BNB/USDT" in client.get("/game/quotes", headers=auth()).json()["symbols"]
    order = {"season": "week", "symbol": "BNB/USDT", "side": "long", "amount_usdt": 100}
    assert client.post("/game/orders", json=order, headers=auth()).status_code == 200


def test_order_returns_tips(client):
    order = {"season": "week", "symbol": "BTC/USDT", "side": "long", "amount_usdt": 4000}
    body = client.post("/game/orders", json=order, headers=auth()).json()
    assert body["tips"] == [{"code": "no_stop", "lesson_id": "04"}, {"code": "big_position", "lesson_id": "03"}]


def _closed_position(client, clock):
    order = {"season": "week", "symbol": "BTC/USDT", "side": "long", "amount_usdt": 1000}
    position = client.post("/game/orders", json=order, headers=auth()).json()
    client.post(f"/game/positions/{position['id']}/close", headers=auth())
    return position["id"]


def test_review_own_closed_position(client, clock):
    position_id = _closed_position(client, clock)
    response = client.get(f"/game/positions/{position_id}/review", headers=auth())
    assert response.status_code == 200
    body = response.json()
    assert body["position_id"] == position_id
    assert body["result"]["close_reason"] == "manual"
    assert body["entry"] is None
    assert "no_stop_loss" in body["notes"]


def test_review_foreign_or_open_is_404(client, clock):
    position_id = _closed_position(client, clock)
    assert client.get(f"/game/positions/{position_id}/review", headers=auth(BOB)).status_code == 404
    order = {"season": "week", "symbol": "ETH/USDT", "side": "long", "amount_usdt": 100}
    open_id = client.post("/game/orders", json=order, headers=auth()).json()["id"]
    assert client.get(f"/game/positions/{open_id}/review", headers=auth()).status_code == 404
    assert client.get("/game/positions/9999/review", headers=auth()).status_code == 404
