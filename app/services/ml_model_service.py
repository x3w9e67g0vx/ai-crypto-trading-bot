from __future__ import annotations

import time
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sqlalchemy.orm import Session

from app.db.models import ModelTrainingRun
from app.services.ml_dataset_service import MLDatasetService


class MLModelService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.dataset_service = MLDatasetService(db)

        self.model_dir = Path("artifacts/models")
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def get_model_path(self, model_type: str) -> Path:
        return self.model_dir / f"{model_type}_model.joblib"

    def get_features_path(self, model_type: str) -> Path:
        return self.model_dir / f"{model_type}_features.joblib"

    def get_feature_columns(self, df: pd.DataFrame) -> list[str]:
        exclude_columns = {
            "candle_id",
            "timestamp",
            "symbol",
            "timeframe",
            "future_close",
            "future_return",
            "target",
        }

        return [col for col in df.columns if col not in exclude_columns]

    def train_model(
        self,
        model_type: str,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 1,
        test_size: float = 0.2,
        random_state: int = 42,
        target_threshold: float = 0.002,
    ) -> dict[str, object]:
        df = self.dataset_service.prepare_dataset(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            target_threshold=target_threshold,
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

        if model_type == "logistic_regression":
            model = LogisticRegression(
                max_iter=1000,
                class_weight="balanced",
            )
            model_name = "LogisticRegression"
        elif model_type == "random_forest":
            model = RandomForestClassifier(
                n_estimators=200,
                max_depth=8,
                min_samples_split=10,
                min_samples_leaf=5,
                class_weight="balanced",
                random_state=random_state,
                n_jobs=-1,
            )
            model_name = "RandomForest"
        else:
            return {
                "status": "error",
                "message": f"Unsupported model_type: {model_type}",
            }

        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        report = classification_report(
            y_test, y_pred, output_dict=True, zero_division=0
        )

        model_path = self.get_model_path(model_type)
        features_path = self.get_features_path(model_type)

        joblib.dump(model, model_path)
        joblib.dump(feature_columns, features_path)

        training_run = ModelTrainingRun(
            model_type=model_name,
            symbol=symbol,
            timeframe=timeframe,
            rows=len(df),
            train_rows=len(X_train),
            test_rows=len(X_test),
            lag_periods=lag_periods,
            future_steps=future_steps,
            accuracy=float(accuracy),
            precision=float(precision),
            recall=float(recall),
            model_path=str(model_path),
            created_at=int(time.time() * 1000),
        )

        self.db.add(training_run)
        self.db.commit()
        self.db.refresh(training_run)

        return {
            "status": "ok",
            "model_type": model_name,
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
            "model_path": str(model_path),
            "training_run_id": training_run.id,
        }

    def train_logistic_regression(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 1,
        test_size: float = 0.2,
        random_state: int = 42,
        target_threshold: float = 0.002,
    ) -> dict[str, object]:
        return self.train_model(
            model_type="logistic_regression",
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            test_size=test_size,
            random_state=random_state,
            target_threshold=target_threshold,
        )

    def load_model(self, model_type: str = "logistic_regression"):
        model_path = self.get_model_path(model_type)
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        return joblib.load(model_path)

    def load_feature_columns(
        self, model_type: str = "logistic_regression"
    ) -> list[str]:
        features_path = self.get_features_path(model_type)
        if not features_path.exists():
            raise FileNotFoundError(f"Feature list file not found: {features_path}")
        return joblib.load(features_path)

    def prepare_features_and_target(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        model_type: str = "logistic_regression",
        target_threshold: float = 0.002,
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        df = self.dataset_service.prepare_dataset(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            target_threshold=target_threshold,
            dropna=True,
        )

        if df.empty:
            raise ValueError("Dataset is empty")

        feature_columns = self.load_feature_columns(model_type=model_type)
        X = df[feature_columns]
        y = df["target"]

        return X, y, df

    def get_latest_features(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        model_type: str = "logistic_regression",
        target_threshold: float = 0.002,
    ) -> tuple[pd.DataFrame, dict[str, object]]:
        df = self.dataset_service.prepare_dataset(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            target_threshold=target_threshold,
            dropna=True,
        )

        if df.empty:
            raise ValueError("Dataset is empty")

        feature_columns = self.load_feature_columns(model_type=model_type)

        latest_row = df.iloc[-1].copy()
        X_latest = df[feature_columns].tail(1)

        meta = {
            "timestamp": int(latest_row["timestamp"]),
            "close": float(latest_row["close"]),
            "symbol": str(latest_row["symbol"]),
            "timeframe": str(latest_row["timeframe"]),
            "rsi": float(latest_row["rsi"])
            if "rsi" in latest_row and pd.notna(latest_row["rsi"])
            else None,
            "ema_fast": float(latest_row["ema_fast"])
            if "ema_fast" in latest_row and pd.notna(latest_row["ema_fast"])
            else None,
            "ema_slow": float(latest_row["ema_slow"])
            if "ema_slow" in latest_row and pd.notna(latest_row["ema_slow"])
            else None,
            "macd": float(latest_row["macd"])
            if "macd" in latest_row and pd.notna(latest_row["macd"])
            else None,
        }

        return X_latest, meta

    def predict_latest(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        model_type: str = "logistic_regression",
        target_threshold: float = 0.002,
    ) -> dict[str, object]:
        model = self.load_model(model_type=model_type)

        X_latest, meta = self.get_latest_features(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            model_type=model_type,
            target_threshold=target_threshold,
        )

        prediction = model.predict(X_latest)[0]
        probabilities = model.predict_proba(X_latest)[0]

        probability_down = float(probabilities[0])
        probability_up = float(probabilities[1])

        return {
            "status": "ok",
            "model_type": model_type,
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": meta["timestamp"],
            "close": meta["close"],
            "rsi": meta["rsi"],
            "ema_fast": meta["ema_fast"],
            "ema_slow": meta["ema_slow"],
            "macd": meta["macd"],
            "prediction": int(prediction),
            "probability_up": probability_up,
            "probability_down": probability_down,
        }

    def get_recent_training_runs(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        query = self.db.query(ModelTrainingRun)

        if symbol:
            query = query.filter(ModelTrainingRun.symbol == symbol)

        if timeframe:
            query = query.filter(ModelTrainingRun.timeframe == timeframe)

        runs = query.order_by(ModelTrainingRun.created_at.desc()).limit(limit).all()

        return [
            {
                "id": run.id,
                "model_type": run.model_type,
                "symbol": run.symbol,
                "timeframe": run.timeframe,
                "rows": run.rows,
                "train_rows": run.train_rows,
                "test_rows": run.test_rows,
                "lag_periods": run.lag_periods,
                "future_steps": run.future_steps,
                "accuracy": run.accuracy,
                "precision": run.precision,
                "recall": run.recall,
                "model_path": run.model_path,
                "created_at": run.created_at,
            }
            for run in runs
        ]
