from tests.api.conftest import auth


def test_old_endpoints_removed(client):
    for path in ("/strategy/signals", "/paper-trading/portfolio", "/miniapp/api/me", "/backtest/run"):
        assert client.get(path, headers=auth()).status_code == 404, path


def test_data_routes_removed(client):
    assert client.post("/ingest/update-multiple", headers=auth()).status_code == 404
    assert client.post("/indicators/calculate-multiple", headers=auth()).status_code == 404


def test_miniapp_served(client):
    response = client.get("/miniapp")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
