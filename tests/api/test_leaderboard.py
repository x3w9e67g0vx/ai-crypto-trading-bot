from app.game.ai_personas import ensure_ai_players
from app.game.config import SeasonKind
from app.game.models import AiDecision, Player, Position
from app.game.seasons import ensure_current_season, join_season
from tests.api.conftest import ALICE, BOB, auth
from tests.game.conftest import NOW

CAROL = {"id": 1003, "username": "carol", "language_code": "en"}
MINUTE = 60 * 1000


def _join_ai(db, kind=SeasonKind.WEEK):
    lstm = ensure_ai_players(db, NOW)["lstm"]
    portfolio = join_season(db, lstm, ensure_current_season(db, kind, NOW), NOW)
    db.commit()
    return lstm, portfolio


def _qualify(client, user=ALICE, season="week"):
    for _ in range(3):
        opened = client.post(
            "/game/orders",
            json={"season": season, "symbol": "BTC/USDT", "side": "long", "amount_usdt": 100},
            headers=auth(user),
        ).json()
        client.post(f"/game/positions/{opened['id']}/close", headers=auth(user))


def _setup_players(client, db):
    # Carol already plays in silver, so she lands in another week group.
    db.add(Player(telegram_id=CAROL["id"], nickname="carol", league_tier="silver", created_at=NOW))
    db.commit()
    for user in (ALICE, BOB, CAROL):
        client.get("/game/me", headers=auth(user))


def test_week_leaderboard_is_my_group_with_ai_ghosts(client, db):
    _setup_players(client, db)
    _join_ai(db)
    _qualify(client)

    body = client.get("/game/leaderboard", params={"season": "week"}, headers=auth()).json()

    assert body["scope"] == "group"
    assert body["tier"] == "bronze"
    rows = {row["nickname"]: row for row in body["rows"]}
    assert set(rows) == {"alice", "Bob", "LSTM"}
    assert rows["alice"]["is_me"] is True
    assert rows["alice"]["rank"] == 1
    assert rows["alice"]["qualified"] is True
    assert rows["LSTM"]["is_ai"] is True
    assert rows["LSTM"]["rank"] is None
    assert rows["Bob"]["is_me"] is False


def test_sprint_leaderboard_global_marks_me(client, db):
    _setup_players(client, db)

    body = client.get("/game/leaderboard", params={"season": "sprint"}, headers=auth(BOB)).json()

    assert body["scope"] == "global"
    assert body["tier"] is None
    assert {row["nickname"] for row in body["rows"]} == {"alice", "Bob", "carol"}
    assert [row["nickname"] for row in body["rows"] if row["is_me"]] == ["Bob"]


def test_ai_endpoint_delays_for_free(client, db):
    lstm, portfolio = _join_ai(db)
    db.add(Position(portfolio_id=portfolio.id, symbol="BTC/USDT", side="long", qty=1, entry_price=100, reserved=100, opened_at=NOW - 20 * MINUTE))
    for minutes_ago in (120, 20):
        db.add(AiDecision(player_id=lstm.id, symbol="BTC/USDT", candle_ts=NOW - minutes_ago * MINUTE, probability_up=0.7, view="bullish", created_at=NOW - minutes_ago * MINUTE))
    db.commit()

    free = client.get("/game/ai", params={"season": "week"}, headers=auth()).json()

    persona = next(row for row in free if row["key"] == "lstm")
    assert persona["nickname"] == "LSTM"
    assert persona["delayed"] is True
    assert persona["positions"] == []
    assert [decision["created_at"] for decision in persona["decisions"]] == [NOW - 120 * MINUTE]

    db.query(Player).filter_by(telegram_id=ALICE["id"]).update({"is_pro_until": NOW + MINUTE})
    db.commit()
    pro = next(row for row in client.get("/game/ai", params={"season": "week"}, headers=auth()).json() if row["key"] == "lstm")

    assert pro["delayed"] is False
    assert [position["symbol"] for position in pro["positions"]] == ["BTC/USDT"]
    assert len(pro["decisions"]) == 2
