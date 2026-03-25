from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.db.models import Candle, Indicator


class MLDatasetService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def load_base_dataframe(self, symbol: str, timeframe: str) -> pd.DataFrame:
        query = (
            self.db.query(Candle, Indicator)
            .outerjoin(Indicator, Indicator.candle_id == Candle.id)
            .filter(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
            )
            .order_by(Candle.timestamp.asc())
        )

        rows = query.all()

        data = []
        for candle, indicator in rows:
            data.append(
                {
                    "candle_id": candle.id,
                    "timestamp": candle.timestamp,
                    "symbol": candle.symbol,
                    "timeframe": candle.timeframe,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                    "rsi": indicator.rsi if indicator else None,
                    "ema_fast": indicator.ema_fast if indicator else None,
                    "ema_slow": indicator.ema_slow if indicator else None,
                    "macd": indicator.macd if indicator else None,
                    "bollinger_upper": indicator.bollinger_upper if indicator else None,
                    "bollinger_lower": indicator.bollinger_lower if indicator else None,
                }
            )

        return pd.DataFrame(data)

    def add_basic_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()

        df["return_1"] = df["close"].pct_change(1)
        df["return_3"] = df["close"].pct_change(3)
        df["return_5"] = df["close"].pct_change(5)

        df["high_low_spread"] = df["high"] - df["low"]
        df["open_close_spread"] = df["close"] - df["open"]

        return df

    def add_lag_features(self, df: pd.DataFrame, lag_periods: int = 3) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()

        lag_columns = [
            "close",
            "volume",
            "rsi",
            "macd",
            "ema_fast",
            "ema_slow",
        ]

        for col in lag_columns:
            for lag in range(1, lag_periods + 1):
                df[f"{col}_lag_{lag}"] = df[col].shift(lag)

        return df

    def add_target(self, df: pd.DataFrame, future_steps: int = 1) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()

        df["future_close"] = df["close"].shift(-future_steps)
        df["target"] = (df["future_close"] > df["close"]).astype(int)

        return df

    def prepare_dataset(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 1,
        dropna: bool = True,
    ) -> pd.DataFrame:
        df = self.load_base_dataframe(symbol=symbol, timeframe=timeframe)

        if df.empty:
            return df

        df = self.add_basic_features(df)
        df = self.add_lag_features(df, lag_periods=lag_periods)
        df = self.add_target(df, future_steps=future_steps)

        if dropna:
            df = df.dropna().reset_index(drop=True)

        return df
