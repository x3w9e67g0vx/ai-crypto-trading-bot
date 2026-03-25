from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sqlalchemy.orm import Session

from app.services.ml_dataset_service import MLDatasetService


class MLModelService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.dataset_service = MLDatasetService(db)

        self.model_dir = Path("artifacts/models")
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.model_path = self.model_dir / "logistic_regression_model.joblib"
        self.features_path = self.model_dir / "logistic_regression_features.joblib"

    def get_feature_columns(self, df: pd.DataFrame) -> list[str]:
        exclude_columns = {
            "candle_id",
            "timestamp",
            "symbol",
            "timeframe",
            "future_close",
            "target",
        }

        return [col for col in df.columns if col not in exclude_columns]

    def train_logistic_regression(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 1,
        test_size: float = 0.2,
        random_state: int = 42,
    ) -> dict[str, object]:
        df = self.dataset_service.prepare_dataset(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            dropna=True,
        )

        if df.empty:
            return {
                "status": "error",
                "message": "Dataset is empty",
            }

        feature_columns = self.get_feature_columns(df)

        X = df[feature_columns]
        y = df["target"]

        if len(X) < 20:
            return {
                "status": "error",
                "message": "Not enough data to train model",
                "rows": len(X),
            }

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=test_size,
            random_state=random_state,
            shuffle=False,
        )

        model = LogisticRegression(max_iter=1000)
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)

        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)

        report = classification_report(
            y_test, y_pred, output_dict=True, zero_division=0
        )

        joblib.dump(model, self.model_path)
        joblib.dump(feature_columns, self.features_path)

        return {
            "status": "ok",
            "model_type": "LogisticRegression",
            "symbol": symbol,
            "timeframe": timeframe,
            "rows": len(df),
            "train_rows": len(X_train),
            "test_rows": len(X_test),
            "lag_periods": lag_periods,
            "future_steps": future_steps,
            "features": feature_columns,
            "metrics": {
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
            },
            "classification_report": report,
            "model_path": str(self.model_path),
        }

    def load_model(self):
        if not self.model_path.exists():
            raise FileNotFoundError("Model file not found")

        return joblib.load(self.model_path)

    def load_feature_columns(self) -> list[str]:
        if not self.features_path.exists():
            raise FileNotFoundError("Feature list file not found")

        return joblib.load(self.features_path)

    def get_latest_features(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
    ) -> tuple[pd.DataFrame, dict[str, object]]:
        df = self.dataset_service.prepare_dataset(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            dropna=True,
        )

        if df.empty:
            raise ValueError("Dataset is empty")

        feature_columns = self.load_feature_columns()

        latest_row = df.iloc[-1].copy()
        X_latest = df[feature_columns].tail(1)

        meta = {
            "timestamp": int(latest_row["timestamp"]),
            "close": float(latest_row["close"]),
            "symbol": str(latest_row["symbol"]),
            "timeframe": str(latest_row["timeframe"]),
        }

        return X_latest, meta

    def predict_latest(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
    ) -> dict[str, object]:
        model = self.load_model()

        X_latest, meta = self.get_latest_features(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
        )

        prediction = model.predict(X_latest)[0]
        probabilities = model.predict_proba(X_latest)[0]

        probability_down = float(probabilities[0])
        probability_up = float(probabilities[1])

        return {
            "status": "ok",
            "model_type": "LogisticRegression",
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": meta["timestamp"],
            "close": meta["close"],
            "prediction": int(prediction),
            "probability_up": probability_up,
            "probability_down": probability_down,
        }

    def prepare_features_and_target(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        df = self.dataset_service.prepare_dataset(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            dropna=True,
        )

        if df.empty:
            raise ValueError("Dataset is empty")

        feature_columns = self.load_feature_columns()
        X = df[feature_columns]
        y = df["target"]

        return X, y, df
