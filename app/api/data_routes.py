"""Candle and indicator refresh, called by Airflow until the in-app scheduler (phase 7)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db.dependencies import get_db
from app.services.indicator_service import IndicatorService
from app.services.ingestion_service import IngestionService

router = APIRouter(tags=["data"])


def _symbol_list(symbols: str | None) -> list[str]:
    if symbols:
        return [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]
    return settings.get_default_symbols()


@router.post("/ingest/update-multiple")
def update_multiple_symbols(
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=100, ge=1, le=1000),
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return IngestionService(db).ingest_multiple_symbols(
        symbols=_symbol_list(symbols),
        timeframe=timeframe,
        limit=limit,
    )


@router.post("/indicators/calculate-multiple")
def calculate_multiple_indicators(
    timeframe: str = Query(default="5m"),
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return IndicatorService(db).calculate_and_save_multiple(
        symbols=_symbol_list(symbols),
        timeframe=timeframe,
    )
