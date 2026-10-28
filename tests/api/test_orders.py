import pytest

import app.game.trading as trading
from app.game.models import Position
from app.game.quotes import Quote
from tests.api.conftest import BOB, auth
from tests.game.conftest import NOW


def _order(client, user=None, **kw):
    body = {"season": "week", "symbol": "BTC/USDT", "side": "long", "amount_usdt": 1000}
    body.update(kw)
    return client.post("/game/orders", json=body, headers=auth(user) if user else auth())


def _cash(client, kind="week"):
    return client.get("/game/me", headers=auth()).json()["portfolios"][kind]["cash"]


def test_open_long_and_close(client):
    response = _order(client, stop_loss=90, take_profit=120)

    assert response.status_code == 200
    position = response.json()
    assert position["symbol"] == "BTC/USDT"
    assert position["side"] == "long"
    assert position["qty"] == pytest.approx(1000 / 101)
    assert position["entry_price"] == 101
    assert position["stop_loss"] == 90
    assert position["take_profit"] == 120
    assert position["closed_at"] is None
    assert _cash(client) == pytest.approx(10_000 - 1001)
    assert _cash(client, "sprint") == 10_000

    closed = client.post(f"/game/positions/{position['id']}/close", headers=auth())

    assert closed.status_code == 200
    assert closed.json()["closed_at"] == NOW
    assert closed.json()["exit_price"] == 99
    assert closed.json()["close_reason"] == "manual"
    assert closed.json()["pnl"] == pytest.approx(1000 / 101 * 99 * 0.999 - 1001)


def test_locked_symbol_rejected(client):
    response = _order(client, symbol="BNB/USDT")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "symbol_locked"

    assert _order(client, symbol="FAKE/USDT").json()["detail"]["code"] == "unknown_symbol"


def test_game_rule_maps_to_409(client):
    response = _order(client, amount_usdt=6000)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pair_limit_exceeded"
    assert _cash(client) == 10_000


def test_order_on_stale_quote_is_503(client, clock):
    clock["now"] = NOW + 30_001

    response = _order(client)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "stale_quote"
    assert _cash(client) == 10_000


def test_concurrent_open_maps_to_position_exists(client, db, monkeypatch):
    assert _order(client).status_code == 200
    # The second request passed the engine's check before the first committed.
    monkeypatch.setattr(trading, "open_positions", lambda portfolio: [])

    response = _order(client)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "position_exists"
    assert db.query(Position).filter(Position.closed_at.is_(None)).count() == 1


def test_cannot_close_foreign_position(client, db):
    position_id = _order(client).json()["id"]

    for target in (position_id, 9999):
        response = client.post(f"/game/positions/{target}/close", headers=auth(BOB))
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "position_not_found"

    assert db.get(Position, position_id).closed_at is None


def test_positions_open_and_closed(client, quotes, clock):
    btc = _order(client).json()
    eth = _order(client, symbol="ETH/USDT").json()
    client.post(f"/game/positions/{eth['id']}/close", headers=auth())
    clock["now"] = NOW + 1000
    quotes.update(Quote("BTC/USDT", bid=110.0, ask=111.0, ts=NOW + 1000))

    open_rows = client.get("/game/positions", params={"season": "week"}, headers=auth()).json()
    closed_rows = client.get("/game/positions", params={"season": "week", "status": "closed"}, headers=auth()).json()

    assert [row["id"] for row in open_rows] == [btc["id"]]
    qty = 1000 / 101
    assert open_rows[0]["value"] == pytest.approx(qty * 110)
    assert open_rows[0]["unrealized_pnl"] == pytest.approx(qty * 110 * 0.999 - 1001)
    assert [row["id"] for row in closed_rows] == [eth["id"]]
    assert closed_rows[0]["pnl"] is not None
    assert client.get("/game/positions", params={"season": "sprint"}, headers=auth()).json() == []


def test_order_logs_trade(client, db):
    from app.game.models import Event

    assert _order(client).status_code == 200
    assert _order(client, symbol="ETH/USDT", amount_usdt=10**9).status_code == 409
    assert [kind for (kind,) in db.query(Event.kind).filter_by(kind="trade")] == ["trade"]


def test_trade_event_failure_is_not_position_exists(client, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    import app.api.game_routes as routes

    def broken_log(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("events"))

    monkeypatch.setattr(routes, "log_event", broken_log)
    response = _order(client)

    assert response.status_code == 200
    assert response.json()["symbol"] == "BTC/USDT"
