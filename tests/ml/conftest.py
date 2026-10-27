import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db.base import Base
import app.core.db  # noqa: F401  registers all models on Base
from app.core.db.models import Candle, Indicator

TIMEFRAME = "5m"
BAR_MS = 5 * 60 * 1000
CANDLES = 400
# 2026-10-26 00:00 UTC.
FIRST_TS = 1_792_972_800_000
LAST_TS = FIRST_TS + (CANDLES - 1) * BAR_MS


def _insert_candles(db, symbol: str, seed: int) -> None:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.004, CANDLES)))
    frame = pd.DataFrame({"close": close})
    frame["open"] = frame["close"].shift(1).fillna(frame["close"])
    frame["high"] = frame[["open", "close"]].max(axis=1) * 1.001
    frame["low"] = frame[["open", "close"]].min(axis=1) * 0.999
    frame["volume"] = rng.uniform(10, 100, CANDLES)

    delta = frame["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    frame["rsi"] = 100 - 100 / (1 + gain / loss)
    frame["ema_fast"] = frame["close"].ewm(span=12).mean()
    frame["ema_slow"] = frame["close"].ewm(span=26).mean()
    frame["macd"] = frame["ema_fast"] - frame["ema_slow"]
    mid = frame["close"].rolling(20).mean()
    std = frame["close"].rolling(20).std()
    frame["bollinger_upper"] = mid + 2 * std
    frame["bollinger_lower"] = mid - 2 * std

    for i, row in frame.iterrows():
        candle = Candle(
            symbol=symbol,
            timeframe=TIMEFRAME,
            timestamp=FIRST_TS + i * BAR_MS,
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
        )
        db.add(candle)
        db.flush()
        indicator_values = {
            key: (None if pd.isna(row[key]) else float(row[key]))
            for key in ("rsi", "ema_fast", "ema_slow", "macd", "bollinger_upper", "bollinger_lower")
        }
        db.add(Indicator(candle_id=candle.id, **indicator_values))
    db.commit()


@pytest.fixture
def candles_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    _insert_candles(session, "BTC/USDT", seed=1)
    _insert_candles(session, "ETH/USDT", seed=2)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def model_dir(tmp_path):
    return tmp_path / "models"
