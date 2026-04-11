from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.db.models import Candle, Indicator


class IndicatorService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_candles_dataframe(self, symbol: str, timeframe: str) -> pd.DataFrame:
        candles = (
            self.db.query(Candle)
            .filter(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
            )
            .order_by(Candle.timestamp.asc())
            .all()
        )

        data = [
            {
                "id": candle.id,
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            for candle in candles
        ]

        return pd.DataFrame(data)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()

        df["ema_fast"] = df["close"].ewm(span=12, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=26, adjust=False).mean()

        df["macd"] = df["ema_fast"] - df["ema_slow"]

        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()

        rs = avg_gain / avg_loss.replace(0, pd.NA)
        df["rsi"] = 100 - (100 / (1 + rs))

        rolling_mean = df["close"].rolling(window=20).mean()
        rolling_std = df["close"].rolling(window=20).std()

        df["bollinger_upper"] = rolling_mean + (2 * rolling_std)
        df["bollinger_lower"] = rolling_mean - (2 * rolling_std)

        return df

    def save_indicators(self, df: pd.DataFrame) -> dict[str, int]:
        if df.empty:
            return {"inserted": 0, "skipped": 0, "total": 0}

        inserted = 0
        skipped = 0

        for _, row in df.iterrows():
            candle_id = int(row["id"])

            exists = (
                self.db.query(Indicator)
                .filter(Indicator.candle_id == candle_id)
                .first()
            )

            if exists:
                skipped += 1
                continue

            indicator = Indicator(
                candle_id=candle_id,
                rsi=float(row["rsi"]) if pd.notna(row["rsi"]) else None,
                ema_fast=float(row["ema_fast"]) if pd.notna(row["ema_fast"]) else None,
                ema_slow=float(row["ema_slow"]) if pd.notna(row["ema_slow"]) else None,
                macd=float(row["macd"]) if pd.notna(row["macd"]) else None,
                bollinger_upper=float(row["bollinger_upper"])
                if pd.notna(row["bollinger_upper"])
                else None,
                bollinger_lower=float(row["bollinger_lower"])
                if pd.notna(row["bollinger_lower"])
                else None,
            )

            self.db.add(indicator)
            inserted += 1

        self.db.commit()

        return {
            "inserted": inserted,
            "skipped": skipped,
            "total": len(df),
        }

    def calculate_and_save(self, symbol: str, timeframe: str) -> dict[str, int | str]:
        df = self.get_candles_dataframe(symbol=symbol, timeframe=timeframe)

        if df.empty:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "inserted": 0,
                "skipped": 0,
                "total": 0,
            }

        df = self.calculate_indicators(df)
        result = self.save_indicators(df)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            **result,
        }

    def calculate_and_save_multiple(
        self,
        symbols: list[str],
        timeframe: str,
    ) -> dict[str, object]:
        results = []

        total_inserted = 0
        total_skipped = 0
        total_rows = 0

        for symbol in symbols:
            result = self.calculate_and_save(symbol=symbol, timeframe=timeframe)
            results.append(result)

            total_inserted += int(result["inserted"])
            total_skipped += int(result["skipped"])
            total_rows += int(result["total"])

        return {
            "timeframe": timeframe,
            "symbols": symbols,
            "count": len(symbols),
            "total_inserted": total_inserted,
            "total_skipped": total_skipped,
            "total_rows": total_rows,
            "results": results,
        }
