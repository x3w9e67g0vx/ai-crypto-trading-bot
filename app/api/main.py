from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.db import models
from app.db.base import Base
from app.db.session import engine
from app.services.market_data_service import MarketDataService

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
