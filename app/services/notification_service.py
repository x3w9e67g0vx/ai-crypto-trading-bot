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
