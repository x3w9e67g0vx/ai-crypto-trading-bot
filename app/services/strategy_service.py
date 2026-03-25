from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Signal
from app.services.ml_model_service import MLModelService


class StrategyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ml_model_service = MLModelService(db)

    def get_last_saved_signal(
        self,
        symbol: str,
        timeframe: str,
    ) -> Signal | None:
        return (
            self.db.query(Signal)
            .filter(
                Signal.symbol == symbol,
                Signal.timeframe == timeframe,
            )
            .order_by(Signal.timestamp.desc())
            .first()
        )

    def generate_signal(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        buy_threshold: float = 0.7,
        sell_threshold: float = 0.3,
        cooldown_ms: int = 15 * 60 * 1000,
        use_trend_filter: bool = True,
    ) -> dict[str, object]:
        prediction_result = self.ml_model_service.predict_latest(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
        )

        probability_up = float(prediction_result["probability_up"])
        probability_down = float(prediction_result["probability_down"])
        close_price = float(prediction_result["close"])
        timestamp = int(prediction_result["timestamp"])
        ema_fast = prediction_result.get("ema_fast")

        signal = "HOLD"
        reasons = []

        # Базовая ML-логика
        if probability_up >= buy_threshold:
            signal = "BUY"
            reasons.append("probability_up_above_buy_threshold")
        elif probability_up <= sell_threshold:
            signal = "SELL"
            reasons.append("probability_up_below_sell_threshold")
        else:
            reasons.append("probability_in_hold_zone")

        # Trend filter
        if use_trend_filter and ema_fast is not None:
            ema_fast = float(ema_fast)

            if signal == "BUY" and close_price <= ema_fast:
                signal = "HOLD"
                reasons.append("buy_blocked_by_trend_filter")

            if signal == "SELL" and close_price >= ema_fast:
                signal = "HOLD"
                reasons.append("sell_blocked_by_trend_filter")

        # Cooldown
        last_signal = self.get_last_saved_signal(symbol=symbol, timeframe=timeframe)
        if last_signal is not None:
            time_diff = timestamp - int(last_signal.timestamp)
            if time_diff < cooldown_ms and signal in {"BUY", "SELL"}:
                signal = "HOLD"
                reasons.append("blocked_by_cooldown")

        return {
            "status": "ok",
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": timestamp,
            "close": close_price,
            "prediction": prediction_result["prediction"],
            "probability_up": probability_up,
            "probability_down": probability_down,
            "rsi": prediction_result.get("rsi"),
            "ema_fast": prediction_result.get("ema_fast"),
            "ema_slow": prediction_result.get("ema_slow"),
            "macd": prediction_result.get("macd"),
            "signal": signal,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "cooldown_ms": cooldown_ms,
            "use_trend_filter": use_trend_filter,
            "reasons": reasons,
        }

    def save_signal(self, signal_data: dict[str, object]) -> dict[str, object]:
        symbol = str(signal_data["symbol"])
        timeframe = str(signal_data["timeframe"])
        timestamp = int(signal_data["timestamp"])

        existing_signal = (
            self.db.query(Signal)
            .filter(
                Signal.symbol == symbol,
                Signal.timeframe == timeframe,
                Signal.timestamp == timestamp,
            )
            .first()
        )

        if existing_signal:
            return {
                "status": "ok",
                "message": "Signal already exists",
                "signal_id": existing_signal.id,
                "symbol": existing_signal.symbol,
                "timeframe": existing_signal.timeframe,
                "timestamp": existing_signal.timestamp,
                "signal": existing_signal.signal,
                "confidence": existing_signal.confidence,
                "price": existing_signal.price,
            }

        db_signal = Signal(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            signal=str(signal_data["signal"]),
            confidence=float(signal_data["probability_up"]),
            price=float(signal_data["close"]),
        )

        self.db.add(db_signal)
        self.db.commit()
        self.db.refresh(db_signal)

        return {
            "status": "ok",
            "message": "Signal saved",
            "signal_id": db_signal.id,
            "symbol": db_signal.symbol,
            "timeframe": db_signal.timeframe,
            "timestamp": db_signal.timestamp,
            "signal": db_signal.signal,
            "confidence": db_signal.confidence,
            "price": db_signal.price,
        }

    def generate_and_save_signal(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        buy_threshold: float = 0.7,
        sell_threshold: float = 0.3,
        cooldown_ms: int = 15 * 60 * 1000,
        use_trend_filter: bool = True,
    ) -> dict[str, object]:
        signal_data = self.generate_signal(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            cooldown_ms=cooldown_ms,
            use_trend_filter=use_trend_filter,
        )

        saved_signal = self.save_signal(signal_data)

        return {
            "generated_signal": signal_data,
            "saved_signal": saved_signal,
        }

    def get_recent_signals(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        query = self.db.query(Signal)

        if symbol:
            query = query.filter(Signal.symbol == symbol)

        if timeframe:
            query = query.filter(Signal.timeframe == timeframe)

        signals = query.order_by(Signal.timestamp.desc()).limit(limit).all()

        return [
            {
                "id": signal.id,
                "symbol": signal.symbol,
                "timeframe": signal.timeframe,
                "timestamp": signal.timestamp,
                "signal": signal.signal,
                "confidence": signal.confidence,
                "price": signal.price,
            }
            for signal in signals
        ]
