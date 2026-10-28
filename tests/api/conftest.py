import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.db  # noqa: F401  registers all models on Base
from app.api.game_deps import get_now_ms, get_quotes
from app.api.main import app
from app.core.config import settings
from app.core.db.base import Base
from app.core.db.dependencies import get_db
from app.game.quotes import Quote, QuoteBook
from tests.game.conftest import NOW

BOT_TOKEN = "123456:test-token"
ALICE = {"id": 1001, "username": "alice", "first_name": "Alice", "language_code": "ru"}
BOB = {"id": 1002, "first_name": "Bob", "language_code": "en"}


def sign_init_data(user: dict, *, token: str = BOT_TOKEN, auth_date: int | None = None) -> str:
    fields = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "q1",
        "user": json.dumps(user, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def auth(user: dict = ALICE) -> dict[str, str]:
    return {"Authorization": f"tma {sign_init_data(user)}"}


@pytest.fixture
def quotes():
    book = QuoteBook()
    for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        book.update(Quote(symbol, bid=99.0, ask=101.0, ts=NOW))
    return book


@pytest.fixture
def clock():
    """Mutable game time; tests move it with clock['now'] = ..."""
    return {"now": NOW}


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def client(session_factory, quotes, clock, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_quotes] = lambda: quotes
    app.dependency_overrides[get_now_ms] = lambda: clock["now"]
    yield TestClient(app)
    app.dependency_overrides.clear()
