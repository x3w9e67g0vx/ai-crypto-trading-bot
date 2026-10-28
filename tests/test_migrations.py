from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.db import LEGACY_TABLES
from app.core.db.base import Base

ROOT = Path(__file__).resolve().parents[1]


def _upgrade(url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'game.db'}"


def test_upgrade_creates_managed_tables(db_url):
    _upgrade(db_url)
    inspector = inspect(create_engine(db_url))

    for table in Base.metadata.sorted_tables:
        if table.name in LEGACY_TABLES:
            assert not inspector.has_table(table.name)
            continue
        assert inspector.has_table(table.name), table.name
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        assert columns == {column.name for column in table.columns}, table.name


def test_upgrade_keeps_existing_candles(db_url):
    engine = create_engine(db_url)
    Base.metadata.tables["candles"].create(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume) "
                "VALUES ('BTC/USDT', '5m', 1, 1, 1, 1, 1, 1)"
            )
        )

    _upgrade(db_url)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM candles")).scalar() == 1


def test_open_position_unique_index(db_url):
    _upgrade(db_url)
    engine = create_engine(db_url)
    insert = text(
        "INSERT INTO positions (portfolio_id, symbol, side, qty, entry_price, reserved, opened_at, closed_at) "
        "VALUES (1, 'BTC/USDT', 'long', 1, 1, 1, 0, :closed_at)"
    )
    with engine.begin() as connection:
        connection.execute(insert, {"closed_at": 5})
        connection.execute(insert, {"closed_at": None})

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert, {"closed_at": None})
