import asyncio
from statistics import mode

from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.base import Base
from app.db.dependencies import get_db
from app.db.session import engine
from app.services.backtest_service import BacktestService
from app.services.indicator_service import IndicatorService
from app.services.ingestion_service import IngestionService
from app.services.market_data_service import MarketDataService
from app.services.ml_dataset_service import MLDatasetService
from app.services.ml_model_service import MLModelService
from app.services.notification_service import NotificationService
from app.services.paper_trading_service import PaperTradingService
from app.services.strategy_service import StrategyService
from app.services.telegram_service import TelegramService

app = FastAPI(title="AI Crypto Trading Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def health_db() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"database": "ok"}


@app.get("/markets")
def get_markets() -> dict[str, list[str]]:
    service = MarketDataService()
    return {"markets": service.get_markets()[:50]}


@app.get("/ohlcv")
def get_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=10, ge=1, le=500),
) -> dict[str, object]:
    service = MarketDataService()
    candles = service.get_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles,
    }


@app.get("/ml/dataset/preview")
def ml_dataset_preview(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=1, ge=1, le=20),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
) -> dict[str, object]:
    service = MLDatasetService(db)
    df = service.prepare_dataset(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        dropna=True,
    )

    preview_columns = [
        "timestamp",
        "close",
        "future_close",
        "target",
        "rsi",
        "macd",
        "ema_fast",
        "ema_slow",
        "close_lag_1",
        "close_lag_2",
        "close_lag_3",
    ]

    available_columns = [col for col in preview_columns if col in df.columns]
    preview = df[available_columns].tail(limit).to_dict(orient="records")

    target_distribution = (
        df["target"].value_counts().sort_index().to_dict()
        if "target" in df.columns and not df.empty
        else {}
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": len(df),
        "future_steps": future_steps,
        "target_distribution": target_distribution,
        "preview": preview,
    }


@app.get("/ml/predict/latest")
def predict_latest(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    db: Session = Depends(get_db),
    model_type: str = Query(default="logistic_regression"),
) -> dict[str, object]:
    service = MLModelService(db)
    return service.predict_latest(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        model_type=model_type,
    )


@app.get("/strategy/signal/latest")
def get_latest_signal(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)
    return service.generate_signal(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        cooldown_ms=cooldown_ms,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        model_type=model_type,
        target_threshold=target_threshold,
    )


@app.get("/strategy/signals")
def get_recent_signals(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)
    signals = service.get_recent_signals(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )

    return {
        "count": len(signals),
        "signals": signals,
    }


@app.get("/paper-trading/portfolio")
def get_paper_portfolio(
    symbol: str = Query(default="BTC/USDT"),
    current_price: float | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = PaperTradingService(db)
    return service.get_portfolio(symbol=symbol, current_price=current_price)


@app.get("/paper-trading/trades")
def get_paper_trades(
    symbol: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = PaperTradingService(db)
    trades = service.get_recent_trades(symbol=symbol, limit=limit)

    return {
        "count": len(trades),
        "trades": trades,
    }


@app.get("/backtest/run")
def run_backtest(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    initial_usdt: float = Query(default=1000.0, gt=0.0),
    trade_fraction: float = Query(default=0.1, gt=0.0, lt=1.0),
    fee_rate: float = Query(default=0.001, ge=0.0, lt=1.0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    cooldown_bars: int = Query(default=3, ge=0, le=100),
    model_type: str = Query(default="logistic_regression"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = BacktestService(db)
    return service.run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        initial_usdt=initial_usdt,
        trade_fraction=trade_fraction,
        fee_rate=fee_rate,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        cooldown_bars=cooldown_bars,
        model_type=model_type,
    )


@app.get("/ml/training-runs")
def get_training_runs(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = MLModelService(db)
    runs = service.get_recent_training_runs(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )

    return {
        "count": len(runs),
        "runs": runs,
    }


@app.post("/ingest/ohlcv")
def ingest_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IngestionService(db)
    result = service.ingest_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        **result,
    }


@app.post("/update/ohlcv")
def update_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IngestionService(db)
    result = service.update_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    return {
        "status": "ok",
        **result,
    }


@app.post("/indicators/calculate")
def calculate_indicators(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IndicatorService(db)
    result = service.calculate_and_save(symbol=symbol, timeframe=timeframe)

    return {
        "status": "ok",
        **result,
    }


@app.post("/ml/train")
def train_ml_model(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    test_size: float = Query(default=0.2, gt=0.0, lt=0.5),
    db: Session = Depends(get_db),
    model_type: str = Query(default="logistic_regression"),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
) -> dict[str, object]:
    service = MLModelService(db)
    result = service.train_model(
        model_type=model_type,
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        test_size=test_size,
    )

    return result


@app.post("/strategy/signal/generate-and-save")
def generate_and_save_signal(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)
    return service.generate_and_save_signal(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        cooldown_ms=cooldown_ms,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        model_type=model_type,
        target_threshold=target_threshold,
    )


@app.post("/paper-trading/execute")
def execute_paper_trade(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    trade_fraction: float = Query(default=0.1, gt=0.0, lt=1.0),
    fee_rate: float = Query(default=0.001, ge=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = PaperTradingService(db)
    return service.execute_latest_signal(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        trade_fraction=trade_fraction,
        fee_rate=fee_rate,
        cooldown_ms=cooldown_ms,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        model_type=model_type,
    )


@app.post("/telegram/send/last-signal")
def send_last_signal_to_telegram(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    buy_threshold: float = Query(default=0.7, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.3, gt=0.0, lt=1.0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if not settings.TELEGRAM_CHAT_ID:
        return {
            "status": "error",
            "message": "TELEGRAM_CHAT_ID is not configured",
        }

    notification_service = NotificationService(db)
    text = notification_service.format_last_signal_message(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
    )

    telegram_service = TelegramService()
    asyncio.run(
        telegram_service.send_message(
            chat_id=int(settings.TELEGRAM_CHAT_ID),
            text=text,
        )
    )

    return {
        "status": "ok",
        "message": "Last signal sent to Telegram",
    }


@app.post("/telegram/send/last-signal-if-actionable")
def send_last_signal_if_actionable(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if not settings.TELEGRAM_CHAT_ID:
        return {
            "status": "error",
            "message": "TELEGRAM_CHAT_ID is not configured",
        }

    notification_service = NotificationService(db)
    should_send, text = (
        notification_service.get_last_saved_signal_message_if_actionable(
            symbol=symbol,
            timeframe=timeframe,
        )
    )

    if not should_send:
        return {
            "status": "ok",
            "sent": False,
            "message": text,
        }

    telegram_service = TelegramService()
    asyncio.run(
        telegram_service.send_message(
            chat_id=int(settings.TELEGRAM_CHAT_ID),
            text=text,
        )
    )

    return {
        "status": "ok",
        "sent": True,
        "message": "Telegram notification sent",
    }


@app.post("/ml/retrain")
def retrain_ml_model(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    test_size: float = Query(default=0.2, gt=0.0, lt=0.5),
    db: Session = Depends(get_db),
    model_type: str = Query(default="logistic_regression"),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
) -> dict[str, object]:
    service = MLModelService(db)
    return service.train_model(
        model_type=model_type,
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        test_size=test_size,
    )


@app.post("/ingest/backfill")
def backfill_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    since: int = Query(..., description="Unix timestamp in milliseconds"),
    batch_limit: int = Query(default=500, ge=1, le=1000),
    max_batches: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IngestionService(db)
    return service.backfill_ohlcv(
        symbol=symbol,
        timeframe=timeframe,
        since=since,
        batch_limit=batch_limit,
        max_batches=max_batches,
    )


@app.post("/paper-trading/execute-manual")
def execute_manual_paper_trade(
    symbol: str = Query(default="BTC/USDT"),
    side: str = Query(..., pattern="^(BUY|SELL|buy|sell)$"),
    price: float = Query(..., gt=0.0),
    trade_fraction: float = Query(default=0.1, gt=0.0, lt=1.0),
    fee_rate: float = Query(default=0.001, ge=0.0, lt=1.0),
    timestamp: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = PaperTradingService(db)
    return service.execute_manual_trade(
        symbol=symbol,
        side=side,
        price=price,
        trade_fraction=trade_fraction,
        fee_rate=fee_rate,
        timestamp=timestamp,
    )
