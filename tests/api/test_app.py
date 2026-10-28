from app.api.main import app
from tests.api.conftest import auth


def test_old_endpoints_removed(client):
    for path in ("/strategy/signals", "/paper-trading/portfolio", "/miniapp/api/me", "/backtest/run"):
        assert client.get(path, headers=auth()).status_code == 404, path


def test_data_routes_kept():
    paths = {route.path for route in app.routes}
    assert {"/ingest/update-multiple", "/indicators/calculate-multiple"} <= paths


def test_miniapp_served(client):
    response = client.get("/miniapp")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
