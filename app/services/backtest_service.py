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
        entry_cooldown_bars: int = 3,
        exit_cooldown_bars: int = 1,
        model_type: str = "logistic_regression",
        stop_loss_pct: float | None = 0.02,
        take_profit_pct: float | None = 0.04,
        min_trade_usdt: float = 10.0,
        min_position_usdt: float = 5.0,
        max_position_fraction: float = 0.3,
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

        last_buy_index = -10_000
        last_sell_index = -10_000

        buy_count = 0
        sell_count = 0
        hold_count = 0
        profitable_trades = 0
        closed_trades = 0
        closed_trade_pnls = []
        winning_trade_pnls = []
        losing_trade_pnls = []

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

            if signal == "BUY" and (i - last_buy_index) < entry_cooldown_bars:
                signal = "HOLD"

            if signal == "SELL" and (i - last_sell_index) < exit_cooldown_bars:
                signal = "HOLD"

            exit_reason = None

            if asset_balance > 0 and average_entry_price is not None:
                if stop_loss_pct is not None:
                    stop_loss_price = average_entry_price * (1 - stop_loss_pct)
                    if price <= stop_loss_price:
                        signal = "SELL"
                        exit_reason = "stop_loss"

                if take_profit_pct is not None and exit_reason is None:
                    take_profit_price = average_entry_price * (1 + take_profit_pct)
                    if price >= take_profit_price:
                        signal = "SELL"
                        exit_reason = "take_profit"

            executed = False
            realized_pnl_delta = 0.0

            if signal == "BUY" and usdt_balance > 0:
                position_value = asset_balance * price
                portfolio_value = usdt_balance + position_value

                max_position_value = portfolio_value * max_position_fraction
                remaining_position_capacity = max_position_value - position_value

                if remaining_position_capacity > 0:
                    usdt_to_spend = usdt_balance * trade_fraction
                    usdt_to_spend = min(usdt_to_spend, remaining_position_capacity)

                    if usdt_to_spend >= min_trade_usdt:
                        fee = usdt_to_spend * fee_rate
                        net_usdt = usdt_to_spend - fee

                        if net_usdt > 0:
                            bought_amount = net_usdt / price

                            previous_asset_balance = asset_balance
                            previous_avg_price = average_entry_price

                            usdt_balance -= usdt_to_spend
                            asset_balance += bought_amount

                            if (
                                previous_asset_balance <= 0
                                or previous_avg_price is None
                            ):
                                average_entry_price = price
                            else:
                                total_cost_before = (
                                    previous_asset_balance * previous_avg_price
                                )
                                total_cost_new = bought_amount * price
                                total_asset_after = (
                                    previous_asset_balance + bought_amount
                                )
                                average_entry_price = (
                                    total_cost_before + total_cost_new
                                ) / total_asset_after

                            executed = True
                            last_buy_index = i
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
                trade_value_usdt = asset_to_sell * price

                if trade_value_usdt >= min_trade_usdt:
                    remaining_asset = asset_balance - asset_to_sell
                    remaining_position_usdt = remaining_asset * price

                    if 0 < remaining_position_usdt < min_position_usdt:
                        asset_to_sell = asset_balance
                        trade_value_usdt = asset_to_sell * price

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
                        winning_trade_pnls.append(realized_pnl_delta)
                    elif realized_pnl_delta < 0:
                        losing_trade_pnls.append(realized_pnl_delta)

                    if asset_balance <= 1e-12:
                        asset_balance = 0.0
                        average_entry_price = None

                    executed = True
                    last_sell_index = i
                    sell_count += 1

                    trades.append(
                        {
                            "timestamp": timestamp,
                            "side": "SELL",
                            "price": price,
                            "amount": asset_to_sell,
                            "fee": fee,
                            "realized_pnl_delta": realized_pnl_delta,
                            "exit_reason": exit_reason,
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

        gross_profit = sum(winning_trade_pnls) if winning_trade_pnls else 0.0
        gross_loss = abs(sum(losing_trade_pnls)) if losing_trade_pnls else 0.0

        avg_win = gross_profit / len(winning_trade_pnls) if winning_trade_pnls else 0.0

        avg_loss = gross_loss / len(losing_trade_pnls) if losing_trade_pnls else 0.0

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        win_rate_ratio = profitable_trades / closed_trades if closed_trades > 0 else 0.0
        loss_rate_ratio = 1.0 - win_rate_ratio if closed_trades > 0 else 0.0

        expectancy = (win_rate_ratio * avg_win) - (loss_rate_ratio * avg_loss)

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
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "max_drawdown_pct": max_drawdown,
            "last_price": final_price,
            "target_threshold": target_threshold,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "use_trend_filter": use_trend_filter,
            "use_rsi_filter": use_rsi_filter,
            "entry_cooldown_bars": entry_cooldown_bars,
            "exit_cooldown_bars": exit_cooldown_bars,
            "preview_trades": trades[-10:],
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "min_trade_usdt": min_trade_usdt,
            "min_position_usdt": min_position_usdt,
            "max_position_fraction": max_position_fraction,
        }

    def compare_models(
        self,
        symbol: str,
        timeframe: str,
        model_types: list[str],
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
        stop_loss_pct: float | None = 0.02,
        take_profit_pct: float | None = 0.04,
        min_trade_usdt: float = 10.0,
        min_position_usdt: float = 5.0,
        entry_cooldown_bars: int = 3,
        exit_cooldown_bars: int = 1,
        max_position_fraction: float = 0.3,
    ) -> dict[str, object]:
        results = []

        for model_type in model_types:
            result = self.run_backtest(
                symbol=symbol,
                timeframe=timeframe,
                lag_periods=lag_periods,
                future_steps=future_steps,
                target_threshold=target_threshold,
                buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
                initial_usdt=initial_usdt,
                trade_fraction=trade_fraction,
                fee_rate=fee_rate,
                use_trend_filter=use_trend_filter,
                use_rsi_filter=use_rsi_filter,
                rsi_overbought=rsi_overbought,
                rsi_oversold=rsi_oversold,
                model_type=model_type,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                min_trade_usdt=min_trade_usdt,
                min_position_usdt=min_position_usdt,
                entry_cooldown_bars=entry_cooldown_bars,
                exit_cooldown_bars=exit_cooldown_bars,
                max_position_fraction=max_position_fraction,
            )

            results.append(result)

        winner = None
        if results:
            winner = max(results, key=lambda x: float(x["final_balance"]))

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "model_count": len(model_types),
            "models": model_types,
            "winner_model_type": winner["model_type"] if winner else None,
            "winner_final_balance": winner["final_balance"] if winner else None,
            "results": results,
        }
