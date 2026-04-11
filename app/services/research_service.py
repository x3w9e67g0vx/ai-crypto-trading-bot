from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.indicator_service import IndicatorService
from app.services.ingestion_service import IngestionService
from app.services.market_data_service import MarketDataService
from app.services.ml_model_service import MLModelService


class ResearchService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ingestion_service = IngestionService(db)
        self.market_data_service = MarketDataService()
        self.indicator_service = IndicatorService(db)
        self.model_training_service = MLModelService(db)

    def prepare_symbol(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
    ) -> dict[str, object]:
        available_symbols = self.market_data_service.get_available_symbols(
            quote="USDT",
            only_active=True,
            spot_only=True,
            limit=5000,
        )

        if symbol not in available_symbols:
            return {
                "status": "error",
                "message": f"Symbol not available on exchange: {symbol}",
                "symbol": symbol,
                "timeframe": timeframe,
            }

        ingest_result = self.ingestion_service.update_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )

        indicator_result = self.indicator_service.calculate_and_save(
            symbol=symbol,
            timeframe=timeframe,
        )

        logistic_result = self.model_training_service.train_model(
            symbol=symbol,
            timeframe=timeframe,
            model_type="logistic_regression",
            lag_periods=lag_periods,
            future_steps=future_steps,
            target_threshold=target_threshold,
        )

        random_forest_result = self.model_training_service.train_model(
            symbol=symbol,
            timeframe=timeframe,
            model_type="random_forest",
            lag_periods=lag_periods,
            future_steps=future_steps,
            target_threshold=target_threshold,
        )
        gradient_boosting_result = self.model_training_service.train_model(
            symbol=symbol,
            timeframe=timeframe,
            model_type="gradient_boosting",
            lag_periods=lag_periods,
            future_steps=future_steps,
            target_threshold=target_threshold,
        )

        return {
            "status": "ok",
            "symbol": symbol,
            "timeframe": timeframe,
            "ingest": ingest_result,
            "indicators": indicator_result,
            "models": {
                "logistic_regression": {
                    "training_run_id": logistic_result.get("training_run_id"),
                    "accuracy": logistic_result.get("metrics", {}).get("accuracy"),
                    "precision": logistic_result.get("metrics", {}).get("precision"),
                    "recall": logistic_result.get("metrics", {}).get("recall"),
                    "model_path": logistic_result.get("model_path"),
                },
                "random_forest": {
                    "training_run_id": random_forest_result.get("training_run_id"),
                    "accuracy": random_forest_result.get("metrics", {}).get("accuracy"),
                    "precision": random_forest_result.get("metrics", {}).get(
                        "precision"
                    ),
                    "recall": random_forest_result.get("metrics", {}).get("recall"),
                    "model_path": random_forest_result.get("model_path"),
                },
                "gradient_boosting": {
                    "training_run_id": gradient_boosting_result.get("training_run_id"),
                    "accuracy": gradient_boosting_result.get("metrics", {}).get(
                        "accuracy"
                    ),
                    "precision": gradient_boosting_result.get("metrics", {}).get(
                        "precision"
                    ),
                    "recall": gradient_boosting_result.get("metrics", {}).get("recall"),
                    "model_path": gradient_boosting_result.get("model_path"),
                },
            },
        }
