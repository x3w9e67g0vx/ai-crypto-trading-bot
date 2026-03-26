from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.paper_trading_service import PaperTradingService
from app.services.strategy_service import StrategyService


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.strategy_service = StrategyService(db)
        self.paper_trading_service = PaperTradingService(db)

    def format_last_signal_message(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        buy_threshold: float = 0.7,
        sell_threshold: float = 0.3,
    ) -> str:
        signal_data = self.strategy_service.generate_signal(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
        )

        return (
            f"📊 Signal for {signal_data['symbol']} [{signal_data['timeframe']}]\n"
            f"Timestamp: {signal_data['timestamp']}\n"
            f"Price: {signal_data['close']}\n"
            f"Prediction: {signal_data['prediction']}\n"
            f"Probability Up: {signal_data['probability_up']:.4f}\n"
            f"Probability Down: {signal_data['probability_down']:.4f}\n"
            f"Signal: {signal_data['signal']}"
        )

    def format_portfolio_message(self, symbol: str) -> str:
        portfolio = self.paper_trading_service.get_portfolio(symbol)

        return (
            f"💼 Portfolio [{portfolio['symbol']}]\n"
            f"USDT Balance: {portfolio['usdt_balance']:.4f}\n"
            f"Asset Balance: {portfolio['asset_balance']:.8f}\n"
            f"Updated At: {portfolio['updated_at']}"
        )

    def format_recent_trades_message(self, symbol: str, limit: int = 5) -> str:
        trades = self.paper_trading_service.get_recent_trades(
            symbol=symbol, limit=limit
        )

        if not trades:
            return f"📭 No trades found for {symbol}"

        lines = [f"🧾 Recent trades for {symbol}:"]
        for trade in trades:
            lines.append(
                f"- {trade['side']} | price={trade['price']:.2f} | "
                f"amount={trade['amount']:.8f} | fee={trade['fee']:.4f}"
            )

        return "\n".join(lines)

    def get_last_saved_signal_message_if_actionable(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1,
    ) -> tuple[bool, str]:
        signals = self.strategy_service.get_recent_signals(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )

        if not signals:
            return False, f"Нет сохранённых сигналов для {symbol} [{timeframe}]"

        signal = signals[0]

        if signal["signal"] == "HOLD":
            return False, (
                f"Последний сигнал для {symbol} [{timeframe}] = HOLD. "
                f"Отправка в Telegram пропущена."
            )

        message = (
            f"🚨 Actionable signal for {signal['symbol']} [{signal['timeframe']}]\n"
            f"Timestamp: {signal['timestamp']}\n"
            f"Signal: {signal['signal']}\n"
            f"Confidence: {signal['confidence']:.4f}\n"
            f"Price: {signal['price']}"
        )

        return True, message

    def format_multi_symbol_signals_summary(
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
        actionable_only: bool = True,
    ) -> tuple[bool, str]:
        scan_result = self.strategy_service.scan_multiple_signals(
            symbols=symbols,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
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

        results = scan_result["results"]

        filtered_results = []
        for item in results:
            if item.get("status") != "ok":
                continue
            if actionable_only and item.get("signal") == "HOLD":
                continue
            filtered_results.append(item)

        if not filtered_results:
            return False, (
                f"📭 No actionable signals\nTimeframe: {timeframe}\nModel: {model_type}"
            )

        lines = [
            f"📊 Signals summary [{timeframe}]",
            f"Model: {model_type}",
            "",
        ]

        for item in filtered_results:
            symbol = item["symbol"]
            signal = item["signal"]
            probability_up = float(item["probability_up"])
            close_price = float(item["close"])
            rsi = item.get("rsi")
            reasons = item.get("reasons", [])

            reason_text = ", ".join(reasons[:2]) if reasons else "no reasons"
            rsi_text = f"{float(rsi):.2f}" if rsi is not None else "n/a"

            lines.append(
                f"{symbol} — {signal}\n"
                f"Price: {close_price:.4f}\n"
                f"ProbUp: {probability_up:.4f}\n"
                f"RSI: {rsi_text}\n"
                f"Why: {reason_text}\n"
            )

        return True, "\n".join(lines)
