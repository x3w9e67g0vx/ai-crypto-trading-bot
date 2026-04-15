from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.db.models import PortfolioState, Trade
from app.services.paper_trade_log_service import PaperTradeLogService
from app.services.strategy_service import StrategyService


class PaperTradingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.strategy_service = StrategyService(db)
        self.paper_trade_log_service = PaperTradeLogService(db)

    def get_or_create_portfolio(
        self,
        symbol: str,
        chat_id: int | None = None,
    ) -> PortfolioState:
        portfolio = (
            self.db.query(PortfolioState)
            .filter(
                PortfolioState.symbol == symbol,
                PortfolioState.chat_id == chat_id,
            )
            .first()
        )

        if portfolio is None:
            portfolio = PortfolioState(
                chat_id=chat_id,
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
        entry_cooldown_ms: int = 15 * 60 * 1000,
        exit_cooldown_ms: int = 5 * 60 * 1000,
        use_trend_filter: bool = True,
        use_rsi_filter: bool = True,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        model_type: str = "logistic_regression",
        stop_loss_pct: float | None = 0.02,
        take_profit_pct: float | None = 0.04,
        min_trade_usdt: float = 10.0,
        min_position_usdt: float = 5.0,
        max_position_fraction: float = 0.3,
        chat_id: int | None = None,
    ) -> dict[str, object]:
        signal_data = self.strategy_service.generate_signal(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            cooldown_ms=max(entry_cooldown_ms, exit_cooldown_ms),
            use_trend_filter=use_trend_filter,
            use_rsi_filter=use_rsi_filter,
            rsi_overbought=rsi_overbought,
            rsi_oversold=rsi_oversold,
            model_type=model_type,
            target_threshold=target_threshold,
            chat_id=chat_id,
        )

        portfolio = self.get_or_create_portfolio(symbol=symbol, chat_id=chat_id)
        signal = str(signal_data["signal"])
        price = float(signal_data["close"])
        timestamp = int(signal_data["timestamp"])

        exit_reason = None

        if portfolio.asset_balance > 0 and portfolio.average_entry_price is not None:
            avg_entry = float(portfolio.average_entry_price)

            if stop_loss_pct is not None:
                stop_loss_price = avg_entry * (1 - stop_loss_pct)
                if price <= stop_loss_price:
                    exit_reason = "stop_loss"
                    signal = "SELL"
                    price = stop_loss_price

            if take_profit_pct is not None and exit_reason is None:
                take_profit_price = avg_entry * (1 + take_profit_pct)
                if price >= take_profit_price:
                    exit_reason = "take_profit"
                    signal = "SELL"
                    price = take_profit_price

        executed = False
        action = "NO_ACTION"
        amount = 0.0
        fee = 0.0
        realized_pnl_delta = 0.0

        if signal == "BUY" and portfolio.usdt_balance > 0:
            position_value = portfolio.asset_balance * price
            portfolio_value = portfolio.usdt_balance + position_value

            max_position_value = portfolio_value * max_position_fraction
            remaining_position_capacity = max_position_value - position_value

            if remaining_position_capacity > 0:
                usdt_to_spend = portfolio.usdt_balance * trade_fraction
                usdt_to_spend = min(usdt_to_spend, remaining_position_capacity)

                if usdt_to_spend >= min_trade_usdt:
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
                            total_cost_before = (
                                previous_asset_balance * previous_avg_price
                            )
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
            trade_value_usdt = asset_to_sell * price

            if trade_value_usdt >= min_trade_usdt:
                remaining_asset = portfolio.asset_balance - asset_to_sell
                remaining_position_usdt = remaining_asset * price

                if 0 < remaining_position_usdt < min_position_usdt:
                    asset_to_sell = portfolio.asset_balance
                    trade_value_usdt = asset_to_sell * price

                if trade_value_usdt >= min_trade_usdt:
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
            trade_record = Trade(
                chat_id=chat_id,
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

        self.paper_trade_log_service.create_log(
            chat_id=chat_id,
            symbol=symbol,
            timeframe=timeframe,
            model_type=str(signal_data.get("model_type", model_type)),
            signal=str(signal_data["signal"]),
            action=str(action),
            executed=bool(executed),
            price=float(price),
            amount=float(amount),
            fee=float(fee),
            realized_pnl_delta=float(realized_pnl_delta),
            probability_up=(
                float(signal_data["probability_up"])
                if signal_data.get("probability_up") is not None
                else None
            ),
            probability_down=(
                float(signal_data["probability_down"])
                if signal_data.get("probability_down") is not None
                else None
            ),
            rsi=(
                float(signal_data["rsi"])
                if signal_data.get("rsi") is not None
                else None
            ),
            ema_fast=(
                float(signal_data["ema_fast"])
                if signal_data.get("ema_fast") is not None
                else None
            ),
            ema_slow=(
                float(signal_data["ema_slow"])
                if signal_data.get("ema_slow") is not None
                else None
            ),
            macd=(
                float(signal_data["macd"])
                if signal_data.get("macd") is not None
                else None
            ),
            buy_threshold=(
                float(signal_data["buy_threshold"])
                if signal_data.get("buy_threshold") is not None
                else None
            ),
            sell_threshold=(
                float(signal_data["sell_threshold"])
                if signal_data.get("sell_threshold") is not None
                else None
            ),
            use_trend_filter=(
                bool(signal_data["use_trend_filter"])
                if signal_data.get("use_trend_filter") is not None
                else None
            ),
            use_rsi_filter=(
                bool(signal_data["use_rsi_filter"])
                if signal_data.get("use_rsi_filter") is not None
                else None
            ),
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            min_trade_usdt=min_trade_usdt,
            min_position_usdt=min_position_usdt,
            max_position_fraction=max_position_fraction,
            trade_id=trade_record.id if trade_record is not None else None,
            exit_reason=exit_reason,
        )

        return {
            "status": "ok",
            "signal": signal,
            "executed": executed,
            "action": action,
            "price": price,
            "amount": amount,
            "fee": fee,
            "realized_pnl_delta": realized_pnl_delta,
            "exit_reason": exit_reason,
            "portfolio": {
                "chat_id": portfolio.chat_id,
                "symbol": portfolio.symbol,
                "usdt_balance": portfolio.usdt_balance,
                "asset_balance": portfolio.asset_balance,
                "average_entry_price": portfolio.average_entry_price,
                "realized_pnl": portfolio.realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "position_value": position_value,
                "portfolio_value": portfolio_value,
                "updated_at": portfolio.updated_at,
                "min_trade_usdt": min_trade_usdt,
                "min_position_usdt": min_position_usdt,
                "max_position_fraction": max_position_fraction,
            },
            "trade_id": trade_record.id if trade_record else None,
        }

    def get_portfolio(
        self,
        symbol: str,
        chat_id: int | None = None,
        current_price: float | None = None,
    ) -> dict[str, object]:
        portfolio = self.get_or_create_portfolio(symbol=symbol, chat_id=chat_id)

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
            "chat_id": portfolio.chat_id,
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
        self,
        symbol: str | None = None,
        chat_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        query = self.db.query(Trade)

        if symbol:
            query = query.filter(Trade.symbol == symbol)

        if chat_id is not None:
            query = query.filter(Trade.chat_id == chat_id)

        trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()

        return [
            {
                "id": trade.id,
                "chat_id": trade.chat_id,
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
        chat_id: int | None = None,
    ) -> dict[str, object]:
        portfolio = self.get_or_create_portfolio(symbol=symbol, chat_id=chat_id)

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
                chat_id=chat_id,
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

        self.paper_trade_log_service.create_log(
            chat_id=chat_id,
            symbol=symbol,
            timeframe="manual",
            model_type="manual",
            signal=side,
            action=side if executed else "NO_ACTION",
            executed=executed,
            price=price,
            amount=amount,
            fee=fee,
            realized_pnl_delta=realized_pnl_delta,
            probability_up=None,
            probability_down=None,
            rsi=None,
            ema_fast=None,
            ema_slow=None,
            macd=None,
            buy_threshold=None,
            sell_threshold=None,
            use_trend_filter=None,
            use_rsi_filter=None,
            stop_loss_pct=None,
            take_profit_pct=None,
            min_trade_usdt=None,
            min_position_usdt=None,
            max_position_fraction=None,
            trade_id=trade_record.id if trade_record else None,
            exit_reason=None,
        )

        return {
            "status": "ok",
            "chat_id": chat_id,
            "symbol": symbol,
            "side": side,
            "executed": executed,
            "price": price,
            "amount": amount,
            "fee": fee,
            "realized_pnl_delta": realized_pnl_delta,
            "trade_id": trade_record.id if trade_record else None,
            "portfolio": {
                "chat_id": portfolio.chat_id,
                "symbol": portfolio.symbol,
                "usdt_balance": portfolio.usdt_balance,
                "asset_balance": portfolio.asset_balance,
                "average_entry_price": portfolio.average_entry_price,
                "realized_pnl": portfolio.realized_pnl,
                "updated_at": portfolio.updated_at,
            },
        }
