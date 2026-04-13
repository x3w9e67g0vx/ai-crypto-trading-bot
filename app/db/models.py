from sqlalchemy import (
    BigInteger,
    Boolean,
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
    candle_id = Column(
        Integer, ForeignKey("candles.id"), nullable=False, index=True, unique=True
    )

    rsi = Column(Float, nullable=True)
    ema_fast = Column(Float, nullable=True)
    ema_slow = Column(Float, nullable=True)
    macd = Column(Float, nullable=True)
    bollinger_upper = Column(Float, nullable=True)
    bollinger_lower = Column(Float, nullable=True)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "timestamp",
            name="uq_signal_symbol_timeframe_timestamp",
        ),
    )

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


class PortfolioState(Base):
    __tablename__ = "portfolio_state"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False, unique=True, index=True)
    usdt_balance = Column(Float, nullable=False, default=1000.0)
    asset_balance = Column(Float, nullable=False, default=0.0)
    average_entry_price = Column(Float, nullable=True)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    updated_at = Column(BigInteger, nullable=False)


class ModelTrainingRun(Base):
    __tablename__ = "model_training_runs"

    id = Column(Integer, primary_key=True, index=True)
    model_type = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, index=True)

    rows = Column(Integer, nullable=False)
    train_rows = Column(Integer, nullable=False)
    test_rows = Column(Integer, nullable=False)

    lag_periods = Column(Integer, nullable=False)
    future_steps = Column(Integer, nullable=False)

    accuracy = Column(Float, nullable=True)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)

    model_path = Column(String, nullable=True)
    created_at = Column(BigInteger, nullable=False, index=True)


class TelegramSubscription(Base):
    __tablename__ = "telegram_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    created_at = Column(BigInteger, nullable=False, index=True)


class StrategyProfile(Base):
    __tablename__ = "strategy_profiles"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, nullable=True, index=True)
    symbol = Column(String, index=True, nullable=False)

    model_type = Column(String, nullable=False, default="random_forest")
    buy_threshold = Column(Float, nullable=False, default=0.6)
    sell_threshold = Column(Float, nullable=False, default=0.4)
    use_trend_filter = Column(Boolean, nullable=False, default=True)
    use_rsi_filter = Column(Boolean, nullable=False, default=True)
    target_threshold = Column(Float, nullable=False, default=0.002)
    cooldown_ms = Column(Integer, nullable=False, default=0)
    stop_loss_pct = Column(Float, nullable=False, default=0.02)
    take_profit_pct = Column(Float, nullable=False, default=0.04)
    min_trade_usdt = Column(Float, nullable=False, default=10.0)
    min_position_usdt = Column(Float, nullable=False, default=5.0)
    max_position_fraction = Column(Float, nullable=False, default=0.3)


class PaperTradeLog(Base):
    __tablename__ = "paper_trade_logs"

    id = Column(Integer, primary_key=True, index=True)

    chat_id = Column(BigInteger, nullable=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, index=True)

    model_type = Column(String, nullable=False)
    signal = Column(String, nullable=False)
    action = Column(String, nullable=False)

    executed = Column(Boolean, nullable=False, default=False)

    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False, default=0.0)
    fee = Column(Float, nullable=False, default=0.0)
    realized_pnl_delta = Column(Float, nullable=False, default=0.0)

    probability_up = Column(Float, nullable=True)
    probability_down = Column(Float, nullable=True)

    rsi = Column(Float, nullable=True)
    ema_fast = Column(Float, nullable=True)
    ema_slow = Column(Float, nullable=True)
    macd = Column(Float, nullable=True)

    buy_threshold = Column(Float, nullable=True)
    sell_threshold = Column(Float, nullable=True)
    use_trend_filter = Column(Boolean, nullable=True)
    use_rsi_filter = Column(Boolean, nullable=True)

    stop_loss_pct = Column(Float, nullable=True)
    take_profit_pct = Column(Float, nullable=True)
    min_trade_usdt = Column(Float, nullable=True)
    min_position_usdt = Column(Float, nullable=True)
    max_position_fraction = Column(Float, nullable=True)

    trade_id = Column(Integer, nullable=True)
    exit_reason = Column(String, nullable=True)

    created_at = Column(BigInteger, nullable=False, index=True)
