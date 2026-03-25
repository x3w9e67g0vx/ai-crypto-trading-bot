from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Candle
from app.services.market_data_service import MarketDataService


class IngestionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.market_data_service = MarketDataService()

    def ingest_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> dict[str, int]:
        candles = self.market_data_service.get_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )

        inserted = 0
        skipped = 0

        for candle in candles:
            exists = (
                self.db.query(Candle)
                .filter(
                    Candle.symbol == symbol,
                    Candle.timeframe == timeframe,
                    Candle.timestamp == candle["timestamp"],
                )
                .first()
            )

            if exists:
                skipped += 1
                continue

            db_candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=candle["timestamp"],
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            )
            self.db.add(db_candle)
            inserted += 1

        self.db.commit()

        return {
            "inserted": inserted,
            "skipped": skipped,
            "total": len(candles),
        }
