from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Candle
from app.services.market_data_service import MarketDataService


class IngestionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.market_data_service = MarketDataService()

    def get_last_candle(
        self,
        symbol: str,
        timeframe: str,
    ) -> Candle | None:
        return (
            self.db.query(Candle)
            .filter(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
            )
            .order_by(Candle.timestamp.desc())
            .first()
        )

    def ingest_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        since: int | None = None,
    ) -> dict[str, int]:
        candles = self.market_data_service.get_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            since=since,
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

    def update_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> dict[str, int | str | None]:
        last_candle = self.get_last_candle(symbol=symbol, timeframe=timeframe)

        since = None
        if last_candle is not None:
            since = last_candle.timestamp + 1

        candles = self.market_data_service.get_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            since=since,
        )

        inserted = 0
        skipped = 0

        for candle in candles:
            if last_candle is not None and candle["timestamp"] <= last_candle.timestamp:
                skipped += 1
                continue

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
            "symbol": symbol,
            "timeframe": timeframe,
            "last_timestamp": last_candle.timestamp if last_candle else None,
            "inserted": inserted,
            "skipped": skipped,
            "fetched": len(candles),
        }

    def backfill_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int,
        batch_limit: int = 500,
        max_batches: int = 10,
    ) -> dict[str, object]:
        total_inserted = 0
        total_skipped = 0
        total_fetched = 0
        current_since = since
        batches_completed = 0
        last_timestamp = None

        for _ in range(max_batches):
            result = self.ingest_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=batch_limit,
                since=current_since,
            )

            fetched = int(result["total"])
            inserted = int(result["inserted"])
            skipped = int(result["skipped"])

            total_fetched += fetched
            total_inserted += inserted
            total_skipped += skipped
            batches_completed += 1

            candles = self.market_data_service.get_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=batch_limit,
                since=current_since,
            )

            if not candles:
                break

            last_timestamp = candles[-1]["timestamp"]

            # если биржа перестала давать новые свечи
            if len(candles) < batch_limit:
                break

            current_since = last_timestamp + 1

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "since": since,
            "batch_limit": batch_limit,
            "max_batches": max_batches,
            "batches_completed": batches_completed,
            "total_fetched": total_fetched,
            "total_inserted": total_inserted,
            "total_skipped": total_skipped,
            "last_timestamp": last_timestamp,
        }
