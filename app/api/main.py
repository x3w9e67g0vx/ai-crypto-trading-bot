from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import Base
from app.db.dependencies import get_db
from app.db.session import engine
from app.services.indicator_service import IndicatorService
from app.services.ingestion_service import IngestionService
from app.services.market_data_service import MarketDataService
from app.services.ml_dataset_service import MLDatasetService

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
) -> dict[str, object]:
    service = MLDatasetService(db)
    df = service.prepare_dataset(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
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
