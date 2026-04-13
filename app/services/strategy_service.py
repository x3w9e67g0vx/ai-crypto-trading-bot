from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.model_profiles import get_model_profile
from app.db.models import Signal
from app.services.lstm_model_service import LSTMModelService
from app.services.ml_model_service import MLModelService
from app.services.strategy_profile_service import StrategyProfileService


class StrategyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ml_model_service = MLModelService(db)
        self.lstm_model_service = LSTMModelService(db)
        self.strategy_profile_service = StrategyProfileService(db)

    def get_recent_signals_multiple(
        self,
        symbols: list[str],
        timeframe: str | None = None,
        limit_per_symbol: int = 5,
    ) -> dict[str, object]:
        results = []
        total_signals = 0

        for symbol in symbols:
            symbol_signals = self.get_recent_signals(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit_per_symbol,
            )

            results.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "count": len(symbol_signals),
                    "signals": symbol_signals,
                }
            )

            total_signals += len(symbol_signals)

        return {
            "count_symbols": len(symbols),
            "total_signals": total_signals,
            "limit_per_symbol": limit_per_symbol,
            "results": results,
        }

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
        target_threshold: float = 0.002,
        buy_threshold: float = 0.6,
        sell_threshold: float = 0.4,
        cooldown_ms: int = 15 * 60 * 1000,
        use_trend_filter: bool = True,
        use_rsi_filter: bool = True,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        model_type: str = "logistic_regression",
    ) -> dict[str, object]:
        resolved = self.resolve_model_config(
            symbol=symbol,
            model_type=model_type,
            target_threshold=target_threshold,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            cooldown_ms=cooldown_ms,
            use_trend_filter=use_trend_filter,
            use_rsi_filter=use_rsi_filter,
        )

        model_type = str(resolved["model_type"])
        target_threshold = float(resolved["target_threshold"])
        buy_threshold = float(resolved["buy_threshold"])
        sell_threshold = float(resolved["sell_threshold"])
        cooldown_ms = int(resolved["cooldown_ms"])
        use_trend_filter = bool(resolved["use_trend_filter"])
        use_rsi_filter = bool(resolved["use_rsi_filter"])

        if model_type == "lstm":
            lstm_result = self.lstm_model_service.predict_latest_probability(
                symbol=symbol,
                timeframe=timeframe,
                lag_periods=lag_periods,
                future_steps=future_steps,
                target_threshold=target_threshold,
            )

            return self._build_signal_from_probability(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=int(lstm_result["timestamp"]),
                close=float(lstm_result["close"]),
                probability_up=float(lstm_result["probability_up"]),
                rsi=float(lstm_result["rsi"])
                if lstm_result["rsi"] is not None
                else None,
                ema_fast=float(lstm_result["ema_fast"])
                if lstm_result["ema_fast"] is not None
                else None,
                ema_slow=float(lstm_result["ema_slow"])
                if lstm_result["ema_slow"] is not None
                else None,
                macd=float(lstm_result["macd"])
                if lstm_result["macd"] is not None
                else None,
                target_threshold=target_threshold,
                buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
                cooldown_ms=cooldown_ms,
                use_trend_filter=use_trend_filter,
                use_rsi_filter=use_rsi_filter,
                rsi_overbought=rsi_overbought,
                rsi_oversold=rsi_oversold,
                model_type=model_type,
            )

        model = self.ml_model_service.load_model(model_type=model_type)

        X, _, df = self.ml_model_service.prepare_features_and_target(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            model_type=model_type,
            target_threshold=target_threshold,
        )

        if df.empty:
            raise ValueError(f"No data available for {symbol} {timeframe}")

        probabilities = model.predict_proba(X)
        latest_probability_up = float(probabilities[-1][1])
        latest_row = df.iloc[-1]

        rsi = float(latest_row["rsi"]) if latest_row["rsi"] is not None else None
        ema_fast = (
            float(latest_row["ema_fast"])
            if latest_row["ema_fast"] is not None
            else None
        )
        ema_slow = (
            float(latest_row["ema_slow"])
            if latest_row["ema_slow"] is not None
            else None
        )
        macd = float(latest_row["macd"]) if latest_row["macd"] is not None else None

        return self._build_signal_from_probability(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=int(latest_row["timestamp"]),
            close=float(latest_row["close"]),
            probability_up=latest_probability_up,
            rsi=rsi,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            macd=macd,
            target_threshold=target_threshold,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            cooldown_ms=cooldown_ms,
            use_trend_filter=use_trend_filter,
            use_rsi_filter=use_rsi_filter,
            rsi_overbought=rsi_overbought,
            rsi_oversold=rsi_oversold,
            model_type=model_type,
        )

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
        buy_threshold: float = 0.6,
        sell_threshold: float = 0.4,
        cooldown_ms: int = 15 * 60 * 1000,
        use_trend_filter: bool = True,
        use_rsi_filter: bool = True,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        model_type: str = "logistic_regression",
        target_threshold: float = 0.002,
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
            use_rsi_filter=use_rsi_filter,
            rsi_overbought=rsi_overbought,
            rsi_oversold=rsi_oversold,
            model_type=model_type,
            target_threshold=target_threshold,
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

    def scan_multiple_signals(
        self,
        symbols: list[str],
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
        buy_threshold: float = 0.6,
        sell_threshold: float = 0.4,
        cooldown_ms: int = 15 * 60 * 1000,
        use_trend_filter: bool = True,
        use_rsi_filter: bool = True,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        model_type: str = "logistic_regression",
    ) -> dict[str, object]:
        results = []

        buy_count = 0
        sell_count = 0
        hold_count = 0

        for symbol in symbols:
            try:
                result = self.generate_signal(
                    symbol=symbol,
                    timeframe=timeframe,
                    lag_periods=lag_periods,
                    future_steps=future_steps,
                    buy_threshold=buy_threshold,
                    sell_threshold=sell_threshold,
                    cooldown_ms=cooldown_ms,
                    use_trend_filter=use_trend_filter,
                    use_rsi_filter=use_rsi_filter,
                    rsi_overbought=rsi_overbought,
                    rsi_oversold=rsi_oversold,
                    model_type=model_type,
                    target_threshold=target_threshold,
                )

                signal = result["signal"]
                if signal == "BUY":
                    buy_count += 1
                elif signal == "SELL":
                    sell_count += 1
                else:
                    hold_count += 1

                results.append(result)

            except Exception as e:
                results.append(
                    {
                        "status": "error",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "error": str(e),
                    }
                )

        return {
            "timeframe": timeframe,
            "model_type": model_type,
            "count": len(symbols),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "hold_count": hold_count,
            "results": results,
        }

    def generate_and_save_multiple_signals(
        self,
        symbols: list[str],
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
        buy_threshold: float = 0.6,
        sell_threshold: float = 0.4,
        cooldown_ms: int = 15 * 60 * 1000,
        use_trend_filter: bool = True,
        use_rsi_filter: bool = True,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        model_type: str = "logistic_regression",
    ) -> dict[str, object]:
        results = []

        buy_count = 0
        sell_count = 0
        hold_count = 0
        saved_count = 0

        for symbol in symbols:
            try:
                result = self.generate_and_save_signal(
                    symbol=symbol,
                    timeframe=timeframe,
                    lag_periods=lag_periods,
                    future_steps=future_steps,
                    buy_threshold=buy_threshold,
                    sell_threshold=sell_threshold,
                    cooldown_ms=cooldown_ms,
                    use_trend_filter=use_trend_filter,
                    use_rsi_filter=use_rsi_filter,
                    rsi_overbought=rsi_overbought,
                    rsi_oversold=rsi_oversold,
                    model_type=model_type,
                    target_threshold=target_threshold,
                )

                generated_signal = result["generated_signal"]
                saved_signal = result["saved_signal"]

                signal = generated_signal["signal"]
                if signal == "BUY":
                    buy_count += 1
                elif signal == "SELL":
                    sell_count += 1
                else:
                    hold_count += 1

                if saved_signal.get("status") == "ok":
                    saved_count += 1

                results.append(result)

            except Exception as e:
                results.append(
                    {
                        "status": "error",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "error": str(e),
                    }
                )

        return {
            "timeframe": timeframe,
            "model_type": model_type,
            "count": len(symbols),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "hold_count": hold_count,
            "saved_count": saved_count,
            "results": results,
        }

    def _build_signal_from_probability(
        self,
        symbol: str,
        timeframe: str,
        timestamp: int,
        close: float,
        probability_up: float,
        rsi: float | None,
        ema_fast: float | None,
        ema_slow: float | None,
        macd: float | None,
        target_threshold: float,
        buy_threshold: float,
        sell_threshold: float,
        cooldown_ms: int,
        use_trend_filter: bool,
        use_rsi_filter: bool,
        rsi_overbought: float,
        rsi_oversold: float,
        model_type: str,
    ) -> dict[str, object]:
        reasons: list[str] = []

        buy_candidate = probability_up >= buy_threshold
        sell_candidate = probability_up <= sell_threshold

        if buy_candidate:
            reasons.append("probability_up_above_buy_threshold")
        elif sell_candidate:
            reasons.append("probability_up_below_sell_threshold")
        else:
            reasons.append("probability_in_hold_zone")

        if use_trend_filter and ema_fast is not None and ema_slow is not None:
            if buy_candidate and not (ema_fast > ema_slow):
                buy_candidate = False
                reasons.append("buy_blocked_by_trend_filter")
            if sell_candidate and not (ema_fast < ema_slow):
                sell_candidate = False
                reasons.append("sell_blocked_by_trend_filter")

        if use_rsi_filter and rsi is not None:
            if buy_candidate and not (rsi < rsi_overbought):
                buy_candidate = False
                reasons.append("buy_blocked_by_rsi_filter")
            if sell_candidate and not (rsi > rsi_oversold):
                sell_candidate = False
                reasons.append("sell_blocked_by_rsi_filter")

        signal = "HOLD"
        if buy_candidate:
            signal = "BUY"
        elif sell_candidate:
            signal = "SELL"

        return {
            "status": "ok",
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": timestamp,
            "close": close,
            "prediction": 1 if probability_up >= 0.5 else 0,
            "probability_up": probability_up,
            "probability_down": 1.0 - probability_up,
            "rsi": rsi,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "macd": macd,
            "signal": signal,
            "model_type": model_type,
            "target_threshold": target_threshold,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "cooldown_ms": cooldown_ms,
            "use_trend_filter": use_trend_filter,
            "use_rsi_filter": use_rsi_filter,
            "rsi_overbought": rsi_overbought,
            "rsi_oversold": rsi_oversold,
            "reasons": reasons,
        }

    def resolve_model_config(
        self,
        symbol: str,
        model_type: str,
        target_threshold: float,
        buy_threshold: float,
        sell_threshold: float,
        cooldown_ms: int,
        use_trend_filter: bool,
        use_rsi_filter: bool,
        chat_id: int | None = None,
    ) -> dict[str, object]:
        if model_type != "auto":
            return {
                "model_type": model_type,
                "target_threshold": target_threshold,
                "buy_threshold": buy_threshold,
                "sell_threshold": sell_threshold,
                "cooldown_ms": cooldown_ms,
                "use_trend_filter": use_trend_filter,
                "use_rsi_filter": use_rsi_filter,
            }

        profile = self.strategy_profile_service.get_profile(
            symbol=symbol,
            chat_id=chat_id,
        )

        return {
            "model_type": profile["model_type"],
            "target_threshold": profile["target_threshold"],
            "buy_threshold": profile["buy_threshold"],
            "sell_threshold": profile["sell_threshold"],
            "cooldown_ms": profile["cooldown_ms"],
            "use_trend_filter": profile["use_trend_filter"],
            "use_rsi_filter": profile["use_rsi_filter"],
        }
