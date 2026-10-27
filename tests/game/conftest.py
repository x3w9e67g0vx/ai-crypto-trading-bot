import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db.base import Base
import app.core.db  # noqa: F401  registers all models on Base
from app.game.config import SeasonKind
from app.game.models import Player, Season
from app.game.quotes import Quote, QuoteBook
from app.game.seasons import season_bounds

# 2026-10-28 12:00 UTC, a Wednesday.
NOW = 1_793_188_800_000


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def quotes():
    book = QuoteBook()
    book.update(Quote("BTC/USDT", bid=99.0, ask=101.0, ts=NOW))
    book.update(Quote("ETH/USDT", bid=99.0, ask=101.0, ts=NOW))
    return book


def make_player(db, **kw):
    kw.setdefault("nickname", "player")
    kw.setdefault("created_at", NOW - 10 * 24 * 60 * 60 * 1000)
    player = Player(**kw)
    db.add(player)
    db.flush()
    return player


def make_season(db, kind=SeasonKind.WEEK, at_ms=NOW):
    starts_at, ends_at = season_bounds(kind, at_ms)
    season = Season(kind=kind.value, starts_at=starts_at, ends_at=ends_at, status="active")
    db.add(season)
    db.flush()
    return season
