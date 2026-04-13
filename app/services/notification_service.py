from __future__ import annotations

from datetime import datetime

import requests
from sqlalchemy.orm import Session

from app.core.model_profiles import get_model_profile, set_model_profile
from app.services.paper_trading_service import PaperTradingService
from app.services.strategy_profile_service import StrategyProfileService
from app.services.strategy_service import StrategyService
from app.services.subscription_service import SubscriptionService


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.strategy_service = StrategyService(db)
        self.paper_trading_service = PaperTradingService(db)
        self.strategy_profile_service = StrategyProfileService(db)

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

    def format_timestamp_ms(self, timestamp_ms: int | None) -> str:
        if not timestamp_ms:
            return "n/a"

        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        return dt.strftime("%Y-%m-%d %H:%M")

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
            ts_text = self.format_timestamp_ms(item.get("timestamp"))

            reason_text = ", ".join(reasons[:2]) if reasons else "no reasons"
            rsi_text = f"{float(rsi):.2f}" if rsi is not None else "n/a"

            lines.append(
                f"{symbol} — {signal}\n"
                f"Time: {ts_text}\n"
                f"Price: {close_price:.4f}\n"
                f"ProbUp: {probability_up:.4f}\n"
                f"RSI: {rsi_text}\n"
                f"Why: {reason_text}\n"
            )

        return True, "\n".join(lines)

    def format_single_symbol_signal_message(
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
    ) -> str:
        if model_type == "lstm":
            result = self._get_lstm_signal_via_api(
                symbol=symbol,
                timeframe=timeframe,
                lag_periods=lag_periods,
                future_steps=future_steps,
                target_threshold=target_threshold,
                buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
                use_trend_filter=use_trend_filter,
                use_rsi_filter=use_rsi_filter,
            )
        else:
            result = self.strategy_service.generate_signal(
                symbol=symbol,
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

        rsi = result.get("rsi")
        rsi_text = f"{float(rsi):.2f}" if rsi is not None else "n/a"
        reasons = ", ".join(result.get("reasons", [])) or "no reasons"

        return (
            f"📈 Signal [{result['symbol']}] ({result['timeframe']})\n"
            f"Model: {result['model_type']}\n"
            f"Signal: {result['signal']}\n"
            f"Price: {float(result['close']):.4f}\n"
            f"ProbUp: {float(result['probability_up']):.4f}\n"
            f"RSI: {rsi_text}\n"
            f"Reasons: {reasons}"
        )

    def format_recent_signals_summary(
        self,
        symbols: list[str],
        timeframe: str | None = None,
        limit_per_symbol: int = 3,
    ) -> str:
        data = self.strategy_service.get_recent_signals_multiple(
            symbols=symbols,
            timeframe=timeframe,
            limit_per_symbol=limit_per_symbol,
        )

        lines = ["🕘 Recent signals summary", ""]

        for item in data["results"]:
            symbol = item["symbol"]
            signals = item["signals"]

            lines.append(f"{symbol}:")

            if not signals:
                lines.append("  No signals")
                lines.append("")
                continue

            for signal in signals:
                ts_text = self.format_timestamp_ms(signal.get("timestamp"))

                lines.append(
                    f"  {signal['signal']} | "
                    f"price={float(signal['price']):.4f} | "
                    f"conf={float(signal['confidence']):.4f} | "
                    f"time={ts_text}"
                )

            lines.append("")

        return "\n".join(lines)

    def format_multi_symbol_signals_summary_for_chat(
        self,
        chat_id: int,
        timeframe: str,
        limit_per_symbol: int = 3,
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
        model_type: str = "auto",
        actionable_only: bool = True,
    ) -> tuple[bool, str, list[str]]:

        sub_service = SubscriptionService(self.db)
        symbols = sub_service.get_symbols_for_chat(chat_id)

        if not symbols:
            return False, "No subscriptions for this chat", []

        should_send, text = self.format_multi_symbol_signals_summary(
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
            actionable_only=actionable_only,
        )

        return should_send, text, symbols

    def format_available_symbols_message(
        self,
        symbols: list[str],
        quote: str | None = "USDT",
    ) -> str:
        if not symbols:
            return "Доступные символы не найдены."

        lines = [
            f"📚 Available symbols ({quote})",
            "",
        ]

        for symbol in symbols:
            lines.append(f"- {symbol}")

        return "\n".join(lines)

    def format_symbol_search_message(
        self,
        query: str,
        symbols: list[str],
    ) -> str:
        if not symbols:
            return f"Ничего не найдено по запросу: {query}"

        lines = [
            f"🔎 Search results: {query}",
            "",
        ]

        for symbol in symbols:
            lines.append(f"- {symbol}")

        return "\n".join(lines)

    def _get_lstm_signal_via_api(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
        buy_threshold: float = 0.55,
        sell_threshold: float = 0.2,
        use_trend_filter: bool = False,
        use_rsi_filter: bool = False,
    ) -> dict[str, object]:
        response = requests.get(
            "http://localhost:8000/strategy/signal/latest-lstm",
            params={
                "symbol": symbol,
                "timeframe": timeframe,
                "lag_periods": lag_periods,
                "future_steps": future_steps,
                "target_threshold": target_threshold,
                "buy_threshold": buy_threshold,
                "sell_threshold": sell_threshold,
                "use_trend_filter": use_trend_filter,
                "use_rsi_filter": use_rsi_filter,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def format_strategy_profile_message(
        self, symbol: str, chat_id: int | None = None
    ) -> str:
        profile = self.strategy_profile_service.get_profile(
            symbol=symbol, chat_id=chat_id
        )

        return (
            f"⚙️ Strategy profile [{symbol}]\n"
            f"Model: {profile['model_type']}\n"
            f"Target threshold: {profile['target_threshold']}\n"
            f"Buy threshold: {profile['buy_threshold']}\n"
            f"Sell threshold: {profile['sell_threshold']}\n"
            f"Trend filter: {profile['use_trend_filter']}\n"
            f"RSI filter: {profile['use_rsi_filter']}\n"
            f"Cooldown ms: {profile['cooldown_ms']}\n"
            f"Stop loss: {profile['stop_loss_pct']}\n"
            f"Take profit: {profile['take_profit_pct']}\n"
            f"Min trade USDT: {profile['min_trade_usdt']}\n"
            f"Min position USDT: {profile['min_position_usdt']}\n"
            f"Max position fraction: {profile['max_position_fraction']}"
        )

    def update_symbol_profile(
        self,
        symbol: str,
        model_type: str,
        buy_threshold: float,
        sell_threshold: float,
        use_trend_filter: bool,
        use_rsi_filter: bool,
        target_threshold: float = 0.002,
        cooldown_ms: int = 0,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
        min_trade_usdt: float = 10.0,
        min_position_usdt: float = 5.0,
        max_position_fraction: float = 0.3,
        chat_id: int | None = None,
    ) -> str:
        profile = self.strategy_profile_service.set_profile(
            symbol=symbol,
            profile_data={
                "model_type": model_type,
                "buy_threshold": buy_threshold,
                "sell_threshold": sell_threshold,
                "use_trend_filter": use_trend_filter,
                "use_rsi_filter": use_rsi_filter,
                "target_threshold": target_threshold,
                "cooldown_ms": cooldown_ms,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "min_trade_usdt": min_trade_usdt,
                "min_position_usdt": min_position_usdt,
                "max_position_fraction": max_position_fraction,
            },
            chat_id=chat_id,
        )

        return (
            f"✅ Profile updated [{symbol}]\n"
            f"Model: {profile['model_type']}\n"
            f"Buy threshold: {profile['buy_threshold']}\n"
            f"Sell threshold: {profile['sell_threshold']}\n"
            f"Trend filter: {profile['use_trend_filter']}\n"
            f"RSI filter: {profile['use_rsi_filter']}"
        )
