from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.ml_model_service import MLModelService


class BacktestService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ml_model_service = MLModelService(db)

    def run_backtest(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
        buy_threshold: float = 0.6,
        sell_threshold: float = 0.4,
        initial_usdt: float = 1000.0,
        trade_fraction: float = 0.1,
        fee_rate: float = 0.001,
        use_trend_filter: bool = True,
        use_rsi_filter: bool = True,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        cooldown_bars: int = 3,
        model_type: str = "logistic_regression",
    ) -> dict[str, object]:
        model = self.ml_model_service.load_model(model_type=model_type)
        X, y, df = self.ml_model_service.prepare_features_and_target(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            model_type=model_type,
            target_threshold=target_threshold,
        )

        probabilities = model.predict_proba(X)

        usdt_balance = initial_usdt
        asset_balance = 0.0
        average_entry_price = None
        realized_pnl = 0.0

        trades = []
        equity_curve = []

        last_action_index = -10_000

        buy_count = 0
        sell_count = 0
        hold_count = 0
        profitable_trades = 0
        closed_trades = 0
        closed_trade_pnls = []

        for i in range(len(df)):
            row = df.iloc[i]

            price = float(row["close"])
            timestamp = int(row["timestamp"])
            probability_up = float(probabilities[i][1])

            rsi = float(row["rsi"]) if row["rsi"] is not None else None
            ema_fast = float(row["ema_fast"]) if row["ema_fast"] is not None else None
            ema_slow = float(row["ema_slow"]) if row["ema_slow"] is not None else None

            buy_candidate = probability_up >= buy_threshold
            sell_candidate = probability_up <= sell_threshold

            if use_trend_filter and ema_fast is not None and ema_slow is not None:
                if buy_candidate and not (ema_fast > ema_slow):
                    buy_candidate = False
                if sell_candidate and not (ema_fast < ema_slow):
                    sell_candidate = False

            if use_rsi_filter and rsi is not None:
                if buy_candidate and not (rsi < rsi_overbought):
                    buy_candidate = False
                if sell_candidate and not (rsi > rsi_oversold):
                    sell_candidate = False

            signal = "HOLD"
            if buy_candidate:
                signal = "BUY"
            elif sell_candidate:
                signal = "SELL"

            if signal in {"BUY", "SELL"} and (i - last_action_index) < cooldown_bars:
                signal = "HOLD"

            executed = False
            realized_pnl_delta = 0.0

            if signal == "BUY" and usdt_balance > 0:
                usdt_to_spend = usdt_balance * trade_fraction
                fee = usdt_to_spend * fee_rate
                net_usdt = usdt_to_spend - fee

                if net_usdt > 0:
                    bought_amount = net_usdt / price

                    previous_asset_balance = asset_balance
                    previous_avg_price = average_entry_price

                    usdt_balance -= usdt_to_spend
                    asset_balance += bought_amount

                    if previous_asset_balance <= 0 or previous_avg_price is None:
                        average_entry_price = price
                    else:
                        total_cost_before = previous_asset_balance * previous_avg_price
                        total_cost_new = bought_amount * price
                        total_asset_after = previous_asset_balance + bought_amount
                        average_entry_price = (
                            total_cost_before + total_cost_new
                        ) / total_asset_after

                    executed = True
                    last_action_index = i
                    buy_count += 1

                    trades.append(
                        {
                            "timestamp": timestamp,
                            "side": "BUY",
                            "price": price,
                            "amount": bought_amount,
                            "fee": fee,
                            "probability_up": probability_up,
                            "rsi": rsi,
                            "ema_fast": ema_fast,
                            "ema_slow": ema_slow,
                        }
                    )

            elif signal == "SELL" and asset_balance > 0:
                asset_to_sell = asset_balance * trade_fraction

                if asset_to_sell > 0:
                    gross_usdt = asset_to_sell * price
                    fee = gross_usdt * fee_rate
                    net_usdt = gross_usdt - fee

                    avg_entry = average_entry_price or price
                    realized_pnl_delta = (price - avg_entry) * asset_to_sell - fee

                    asset_balance -= asset_to_sell
                    usdt_balance += net_usdt
                    realized_pnl += realized_pnl_delta

                    closed_trades += 1
                    closed_trade_pnls.append(realized_pnl_delta)
                    if realized_pnl_delta > 0:
                        profitable_trades += 1

                    if asset_balance <= 1e-12:
                        asset_balance = 0.0
                        average_entry_price = None

                    executed = True
                    last_action_index = i
                    sell_count += 1

                    trades.append(
                        {
                            "timestamp": timestamp,
                            "side": "SELL",
                            "price": price,
                            "amount": asset_to_sell,
                            "fee": fee,
                            "realized_pnl_delta": realized_pnl_delta,
                            "probability_up": probability_up,
                            "rsi": rsi,
                            "ema_fast": ema_fast,
                            "ema_slow": ema_slow,
                        }
                    )

            if not executed:
                hold_count += 1

            unrealized_pnl = 0.0
            if asset_balance > 0 and average_entry_price is not None:
                unrealized_pnl = (price - average_entry_price) * asset_balance

            position_value = asset_balance * price
            portfolio_value = usdt_balance + position_value
            equity_curve.append(portfolio_value)

        final_price = float(df.iloc[-1]["close"])
        final_position_value = asset_balance * final_price
        final_unrealized_pnl = 0.0
        if asset_balance > 0 and average_entry_price is not None:
            final_unrealized_pnl = (final_price - average_entry_price) * asset_balance

        final_balance = usdt_balance + final_position_value
        total_return_pct = ((final_balance - initial_usdt) / initial_usdt) * 100

        peak = equity_curve[0] if equity_curve else initial_usdt
        max_drawdown = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value
            drawdown = ((peak - value) / peak) * 100 if peak > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        win_rate = (
            (profitable_trades / closed_trades * 100) if closed_trades > 0 else 0.0
        )
        average_closed_trade_pnl = (
            sum(closed_trade_pnls) / len(closed_trade_pnls)
            if closed_trade_pnls
            else 0.0
        )

        return {
            "status": "ok",
            "model_type": model_type,
            "symbol": symbol,
            "timeframe": timeframe,
            "rows": len(df),
            "initial_usdt": initial_usdt,
            "final_balance": final_balance,
            "total_return_pct": total_return_pct,
            "realized_pnl": realized_pnl,
            "final_unrealized_pnl": final_unrealized_pnl,
            "final_position_value": final_position_value,
            "open_asset_balance": asset_balance,
            "average_entry_price": average_entry_price,
            "trade_count": len(trades),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "hold_count": hold_count,
            "closed_trades": closed_trades,
            "profitable_trades": profitable_trades,
            "win_rate_pct": win_rate,
            "average_closed_trade_pnl": average_closed_trade_pnl,
            "max_drawdown_pct": max_drawdown,
            "last_price": final_price,
            "target_threshold": target_threshold,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "use_trend_filter": use_trend_filter,
            "use_rsi_filter": use_rsi_filter,
            "cooldown_bars": cooldown_bars,
            "preview_trades": trades[-10:],
        }
