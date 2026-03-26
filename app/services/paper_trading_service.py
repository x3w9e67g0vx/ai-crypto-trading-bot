from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.db.models import PortfolioState, Trade
from app.services.strategy_service import StrategyService


class PaperTradingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.strategy_service = StrategyService(db)

    def get_or_create_portfolio(self, symbol: str) -> PortfolioState:
        portfolio = (
            self.db.query(PortfolioState)
            .filter(PortfolioState.symbol == symbol)
            .first()
        )

        if portfolio is None:
            portfolio = PortfolioState(
                symbol=symbol,
                usdt_balance=1000.0,
                asset_balance=0.0,
                average_entry_price=None,
                realized_pnl=0.0,
                updated_at=int(time.time() * 1000),
            )
            self.db.add(portfolio)
            self.db.commit()
            self.db.refresh(portfolio)

        return portfolio

    def execute_latest_signal(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
        buy_threshold: float = 0.6,
        sell_threshold: float = 0.4,
        trade_fraction: float = 0.1,
        fee_rate: float = 0.001,
        cooldown_ms: int = 15 * 60 * 1000,
        use_trend_filter: bool = True,
        use_rsi_filter: bool = True,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        model_type: str = "logistic_regression",
    ) -> dict[str, object]:
        signal_data = self.strategy_service.generate_signal(
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

        portfolio = self.get_or_create_portfolio(symbol)
        signal = str(signal_data["signal"])
        price = float(signal_data["close"])
        timestamp = int(signal_data["timestamp"])

        executed = False
        action = "NO_ACTION"
        amount = 0.0
        fee = 0.0
        realized_pnl_delta = 0.0

        if signal == "BUY" and portfolio.usdt_balance > 0:
            usdt_to_spend = portfolio.usdt_balance * trade_fraction
            fee = usdt_to_spend * fee_rate
            net_usdt_to_spend = usdt_to_spend - fee

            if net_usdt_to_spend > 0:
                bought_amount = net_usdt_to_spend / price

                previous_asset_balance = portfolio.asset_balance
                previous_avg_price = portfolio.average_entry_price

                portfolio.usdt_balance -= usdt_to_spend
                portfolio.asset_balance += bought_amount

                if previous_asset_balance <= 0 or previous_avg_price is None:
                    portfolio.average_entry_price = price
                else:
                    total_cost_before = previous_asset_balance * previous_avg_price
                    total_cost_new = bought_amount * price
                    total_asset_after = previous_asset_balance + bought_amount
                    portfolio.average_entry_price = (
                        total_cost_before + total_cost_new
                    ) / total_asset_after

                amount = bought_amount
                executed = True
                action = "BUY"

        elif signal == "SELL" and portfolio.asset_balance > 0:
            asset_to_sell = portfolio.asset_balance * trade_fraction

            if asset_to_sell > 0:
                gross_usdt = asset_to_sell * price
                fee = gross_usdt * fee_rate
                net_usdt = gross_usdt - fee

                avg_entry = portfolio.average_entry_price or price
                realized_pnl_delta = (price - avg_entry) * asset_to_sell - fee

                portfolio.asset_balance -= asset_to_sell
                portfolio.usdt_balance += net_usdt
                portfolio.realized_pnl += realized_pnl_delta

                if portfolio.asset_balance <= 1e-12:
                    portfolio.asset_balance = 0.0
                    portfolio.average_entry_price = None

                amount = asset_to_sell
                executed = True
                action = "SELL"

        portfolio.updated_at = int(time.time() * 1000)

        trade_record = None

        if executed:
            position_value = portfolio.asset_balance * price
            portfolio_value = portfolio.usdt_balance + position_value

            trade_record = Trade(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                side=action,
                price=price,
                amount=amount,
                fee=fee,
                balance_after=portfolio.usdt_balance,
            )
            self.db.add(trade_record)

        self.db.add(portfolio)
        self.db.commit()

        if trade_record is not None:
            self.db.refresh(trade_record)
        self.db.refresh(portfolio)

        unrealized_pnl = 0.0
        if portfolio.asset_balance > 0 and portfolio.average_entry_price is not None:
            unrealized_pnl = (
                price - portfolio.average_entry_price
            ) * portfolio.asset_balance

        position_value = portfolio.asset_balance * price
        portfolio_value = portfolio.usdt_balance + position_value

        return {
            "status": "ok",
            "signal": signal,
            "executed": executed,
            "action": action,
            "price": price,
            "amount": amount,
            "fee": fee,
            "realized_pnl_delta": realized_pnl_delta,
            "portfolio": {
                "symbol": portfolio.symbol,
                "usdt_balance": portfolio.usdt_balance,
                "asset_balance": portfolio.asset_balance,
                "average_entry_price": portfolio.average_entry_price,
                "realized_pnl": portfolio.realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "position_value": position_value,
                "portfolio_value": portfolio_value,
                "updated_at": portfolio.updated_at,
            },
            "trade_id": trade_record.id if trade_record else None,
        }

    def get_portfolio(
        self, symbol: str, current_price: float | None = None
    ) -> dict[str, object]:
        portfolio = self.get_or_create_portfolio(symbol)

        position_value = 0.0
        unrealized_pnl = 0.0

        if current_price is not None and portfolio.asset_balance > 0:
            position_value = portfolio.asset_balance * current_price

            if portfolio.average_entry_price is not None:
                unrealized_pnl = (
                    current_price - portfolio.average_entry_price
                ) * portfolio.asset_balance

        portfolio_value = portfolio.usdt_balance + position_value

        return {
            "symbol": portfolio.symbol,
            "usdt_balance": portfolio.usdt_balance,
            "asset_balance": portfolio.asset_balance,
            "average_entry_price": portfolio.average_entry_price,
            "realized_pnl": portfolio.realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "position_value": position_value,
            "portfolio_value": portfolio_value,
            "updated_at": portfolio.updated_at,
        }

    def get_recent_trades(
        self, symbol: str | None = None, limit: int = 20
    ) -> list[dict[str, object]]:
        query = self.db.query(Trade)

        if symbol:
            query = query.filter(Trade.symbol == symbol)

        trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()

        return [
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "timeframe": trade.timeframe,
                "timestamp": trade.timestamp,
                "side": trade.side,
                "price": trade.price,
                "amount": trade.amount,
                "fee": trade.fee,
                "balance_after": trade.balance_after,
            }
            for trade in trades
        ]

    def execute_manual_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        trade_fraction: float = 0.1,
        fee_rate: float = 0.001,
        timestamp: int | None = None,
    ) -> dict[str, object]:
        portfolio = self.get_or_create_portfolio(symbol)

        if timestamp is None:
            timestamp = int(time.time() * 1000)

        side = side.upper()

        executed = False
        amount = 0.0
        fee = 0.0
        realized_pnl_delta = 0.0

        if side == "BUY" and portfolio.usdt_balance > 0:
            usdt_to_spend = portfolio.usdt_balance * trade_fraction
            fee = usdt_to_spend * fee_rate
            net_usdt_to_spend = usdt_to_spend - fee

            if net_usdt_to_spend > 0:
                bought_amount = net_usdt_to_spend / price

                previous_asset_balance = portfolio.asset_balance
                previous_avg_price = portfolio.average_entry_price

                portfolio.usdt_balance -= usdt_to_spend
                portfolio.asset_balance += bought_amount

                if previous_asset_balance <= 0 or previous_avg_price is None:
                    portfolio.average_entry_price = price
                else:
                    total_cost_before = previous_asset_balance * previous_avg_price
                    total_cost_new = bought_amount * price
                    total_asset_after = previous_asset_balance + bought_amount
                    portfolio.average_entry_price = (
                        total_cost_before + total_cost_new
                    ) / total_asset_after

                amount = bought_amount
                executed = True

        elif side == "SELL" and portfolio.asset_balance > 0:
            asset_to_sell = portfolio.asset_balance * trade_fraction

            if asset_to_sell > 0:
                gross_usdt = asset_to_sell * price
                fee = gross_usdt * fee_rate
                net_usdt = gross_usdt - fee

                avg_entry = portfolio.average_entry_price or price
                realized_pnl_delta = (price - avg_entry) * asset_to_sell - fee

                portfolio.asset_balance -= asset_to_sell
                portfolio.usdt_balance += net_usdt
                portfolio.realized_pnl += realized_pnl_delta

                if portfolio.asset_balance <= 1e-12:
                    portfolio.asset_balance = 0.0
                    portfolio.average_entry_price = None

                amount = asset_to_sell
                executed = True

        portfolio.updated_at = int(time.time() * 1000)

        trade_record = None

        if executed:
            trade_record = Trade(
                symbol=symbol,
                timeframe="manual",
                timestamp=timestamp,
                side=side,
                price=price,
                amount=amount,
                fee=fee,
                balance_after=portfolio.usdt_balance,
            )
            self.db.add(trade_record)

        self.db.add(portfolio)
        self.db.commit()

        if trade_record is not None:
            self.db.refresh(trade_record)
        self.db.refresh(portfolio)

        unrealized_pnl = 0.0
        if portfolio.asset_balance > 0 and portfolio.average_entry_price is not None:
            unrealized_pnl = (
                price - portfolio.average_entry_price
            ) * portfolio.asset_balance

        position_value = portfolio.asset_balance * price
        portfolio_value = portfolio.usdt_balance + position_value

        return {
            "status": "ok",
            "side": side,
            "executed": executed,
            "price": price,
            "amount": amount,
            "fee": fee,
            "realized_pnl_delta": realized_pnl_delta,
            "portfolio": {
                "symbol": portfolio.symbol,
                "usdt_balance": portfolio.usdt_balance,
                "asset_balance": portfolio.asset_balance,
                "average_entry_price": portfolio.average_entry_price,
                "realized_pnl": portfolio.realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "position_value": position_value,
                "portfolio_value": portfolio_value,
                "updated_at": portfolio.updated_at,
            },
            "trade_id": trade_record.id if trade_record else None,
        }
