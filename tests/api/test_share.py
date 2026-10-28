import io

from PIL import Image

from app.core.config import settings
from app.game.models import Event
from tests.api.conftest import ALICE, BOB, auth


def _share(client, user=ALICE, season="week"):
    client.get("/game/me", headers=auth(user))
    return client.post("/game/share", json={"season": season}, headers=auth(user))


def test_share_returns_text_link_and_logs_event(client, db, monkeypatch):
    monkeypatch.setattr(settings, "BOT_USERNAME", "veydranox_bot")

    response = _share(client)

    assert response.status_code == 200
    body = response.json()
    assert body["link"].startswith("https://t.me/veydranox_bot?start=ref_")
    assert "VEYDRANOX" in body["text"]
    assert body["image_url"].startswith("/game/share/") and "sig=" in body["image_url"]
    assert db.query(Event).filter_by(kind="share").count() == 1


def test_share_without_bot_username_has_no_link(client, monkeypatch):
    monkeypatch.setattr(settings, "BOT_USERNAME", "")
    assert _share(client, BOB, "sprint").json()["link"] is None


def test_share_card_png(client):
    url = _share(client).json()["image_url"]

    response = client.get(url)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "max-age" in response.headers["cache-control"]
    assert Image.open(io.BytesIO(response.content)).size == (1080, 1920)


def test_share_card_bad_signature_404(client):
    url = _share(client).json()["image_url"]
    path, sig = url.split("?sig=")
    other = path.replace("/share/", "/share/9").replace(".png", "") + ".png"

    assert client.get(path).status_code == 404
    assert client.get(f"{path}?sig={'0' * 32}").status_code == 404
    assert client.get(f"{other}?sig={sig}").status_code == 404
    assert client.get(f"{path}?sig=подпись").status_code == 404
