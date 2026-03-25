from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.base import Base


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "timestamp",
            name="uq_candle_symbol_timeframe_timestamp",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False, index=True)

    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)


class Indicator(Base):
    __tablename__ = "indicators"

    id = Column(Integer, primary_key=True, index=True)
    candle_id = Column(Integer, ForeignKey("candles.id"), nullable=False, index=True)

    rsi = Column(Float, nullable=True)
    ema_fast = Column(Float, nullable=True)
    ema_slow = Column(Float, nullable=True)
    macd = Column(Float, nullable=True)
    bollinger_upper = Column(Float, nullable=True)
    bollinger_lower = Column(Float, nullable=True)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False, index=True)

    signal = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    price = Column(Float, nullable=False)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False, index=True)

    side = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, nullable=True)
    balance_after = Column(Float, nullable=True)
