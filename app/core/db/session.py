import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# For production safety, SQL logging (echo) should be OFF by default.
# Enable it explicitly via environment variable when debugging.
SQLALCHEMY_ECHO = _env_bool("SQLALCHEMY_ECHO", default=False)

engine = create_engine(
    settings.database_url,
    echo=SQLALCHEMY_ECHO,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
