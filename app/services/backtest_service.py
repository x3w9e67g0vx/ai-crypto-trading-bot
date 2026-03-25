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
        buy_threshold: float = 0.7,
        sell_threshold: float = 0.3,
        initial_usdt: float = 1000.0,
        trade_fraction: float = 0.1,
        fee_rate: float = 0.001,
    ) -> dict[str, object]:
        model = self.ml_model_service.load_model()
        X, y, df = self.ml_model_service.prepare_features_and_target(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
        )

        probabilities = model.predict_proba(X)

        usdt_balance = initial_usdt
        asset_balance = 0.0

        trades = []
        equity_curve = []

        for i in range(len(df)):
            row = df.iloc[i]
            price = float(row["close"])
            timestamp = int(row["timestamp"])

            probability_up = float(probabilities[i][1])

            if probability_up >= buy_threshold:
                signal = "BUY"
            elif probability_up <= sell_threshold:
                signal = "SELL"
            else:
                signal = "HOLD"

            executed = False
            pnl = 0.0

            if signal == "BUY" and usdt_balance > 0:
                usdt_to_spend = usdt_balance * trade_fraction
                fee = usdt_to_spend * fee_rate
                net_usdt = usdt_to_spend - fee

                if net_usdt > 0:
                    asset_amount = net_usdt / price
                    usdt_balance -= usdt_to_spend
                    asset_balance += asset_amount
                    executed = True

                    trades.append(
                        {
                            "timestamp": timestamp,
                            "side": "BUY",
                            "price": price,
                            "amount": asset_amount,
                            "fee": fee,
                        }
                    )

            elif signal == "SELL" and asset_balance > 0:
                asset_to_sell = asset_balance * trade_fraction
                gross_usdt = asset_to_sell * price
                fee = gross_usdt * fee_rate
                net_usdt = gross_usdt - fee

                if asset_to_sell > 0:
                    asset_balance -= asset_to_sell
                    usdt_balance += net_usdt
                    executed = True

                    trades.append(
                        {
                            "timestamp": timestamp,
                            "side": "SELL",
                            "price": price,
                            "amount": asset_to_sell,
                            "fee": fee,
                        }
                    )

            portfolio_value = usdt_balance + (asset_balance * price)
            equity_curve.append(portfolio_value)

        final_price = float(df.iloc[-1]["close"])
        final_balance = usdt_balance + (asset_balance * final_price)
        total_return_pct = ((final_balance - initial_usdt) / initial_usdt) * 100

        sell_trades = [trade for trade in trades if trade["side"] == "SELL"]
        winning_sells = 0

        # считаем SELL успешным, если финальный баланс после стратегии не ниже начального
        if final_balance > initial_usdt:
            winning_sells = len(sell_trades)

        winrate = (winning_sells / len(sell_trades) * 100) if sell_trades else 0.0

        peak = equity_curve[0] if equity_curve else initial_usdt
        max_drawdown = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value

            drawdown = ((peak - value) / peak) * 100 if peak > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return {
            "status": "ok",
            "symbol": symbol,
            "timeframe": timeframe,
            "rows": len(df),
            "initial_usdt": initial_usdt,
            "final_balance": final_balance,
            "total_return_pct": total_return_pct,
            "trade_count": len(trades),
            "sell_trade_count": len(sell_trades),
            "winrate": winrate,
            "max_drawdown_pct": max_drawdown,
            "last_price": final_price,
            "preview_trades": trades[-10:],
        }
