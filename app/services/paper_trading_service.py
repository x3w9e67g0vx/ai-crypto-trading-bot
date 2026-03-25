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
        buy_threshold: float = 0.7,
        sell_threshold: float = 0.3,
        trade_fraction: float = 0.1,
        fee_rate: float = 0.001,
    ) -> dict[str, object]:
        signal_data = self.strategy_service.generate_signal(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
        )

        portfolio = self.get_or_create_portfolio(symbol)
        signal = str(signal_data["signal"])
        price = float(signal_data["close"])
        timestamp = int(signal_data["timestamp"])

        executed = False
        action = "NO_ACTION"
        amount = 0.0
        fee = 0.0

        if signal == "BUY" and portfolio.usdt_balance > 0:
            usdt_to_spend = portfolio.usdt_balance * trade_fraction
            fee = usdt_to_spend * fee_rate
            net_usdt_to_spend = usdt_to_spend - fee

            if net_usdt_to_spend > 0:
                amount = net_usdt_to_spend / price
                portfolio.usdt_balance -= usdt_to_spend
                portfolio.asset_balance += amount
                executed = True
                action = "BUY"

        elif signal == "SELL" and portfolio.asset_balance > 0:
            asset_to_sell = portfolio.asset_balance * trade_fraction
            gross_usdt = asset_to_sell * price
            fee = gross_usdt * fee_rate
            net_usdt = gross_usdt - fee

            if asset_to_sell > 0:
                amount = asset_to_sell
                portfolio.asset_balance -= asset_to_sell
                portfolio.usdt_balance += net_usdt
                executed = True
                action = "SELL"

        portfolio.updated_at = int(time.time() * 1000)

        trade_record = None

        if executed:
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

        return {
            "status": "ok",
            "signal": signal,
            "executed": executed,
            "action": action,
            "price": price,
            "amount": amount,
            "fee": fee,
            "portfolio": {
                "symbol": portfolio.symbol,
                "usdt_balance": portfolio.usdt_balance,
                "asset_balance": portfolio.asset_balance,
                "updated_at": portfolio.updated_at,
            },
            "trade_id": trade_record.id if trade_record else None,
        }

    def get_portfolio(self, symbol: str) -> dict[str, object]:
        portfolio = self.get_or_create_portfolio(symbol)

        return {
            "symbol": portfolio.symbol,
            "usdt_balance": portfolio.usdt_balance,
            "asset_balance": portfolio.asset_balance,
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
