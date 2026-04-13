from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.db.models import PaperTradeLog


class PaperTradeLogService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_log(
        self,
        *,
        chat_id: int | None,
        symbol: str,
        timeframe: str,
        model_type: str,
        signal: str,
        action: str,
        executed: bool,
        price: float,
        amount: float,
        fee: float,
        realized_pnl_delta: float,
        probability_up: float | None,
        probability_down: float | None,
        rsi: float | None,
        ema_fast: float | None,
        ema_slow: float | None,
        macd: float | None,
        buy_threshold: float | None,
        sell_threshold: float | None,
        use_trend_filter: bool | None,
        use_rsi_filter: bool | None,
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
        min_trade_usdt: float | None,
        min_position_usdt: float | None,
        max_position_fraction: float | None,
        trade_id: int | None,
        exit_reason: str | None,
    ) -> PaperTradeLog:
        row = PaperTradeLog(
            chat_id=chat_id,
            symbol=symbol,
            timeframe=timeframe,
            model_type=model_type,
            signal=signal,
            action=action,
            executed=executed,
            price=price,
            amount=amount,
            fee=fee,
            realized_pnl_delta=realized_pnl_delta,
            probability_up=probability_up,
            probability_down=probability_down,
            rsi=rsi,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            macd=macd,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            use_trend_filter=use_trend_filter,
            use_rsi_filter=use_rsi_filter,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            min_trade_usdt=min_trade_usdt,
            min_position_usdt=min_position_usdt,
            max_position_fraction=max_position_fraction,
            trade_id=trade_id,
            exit_reason=exit_reason,
            created_at=int(time.time() * 1000),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_recent_logs(
        self,
        *,
        symbol: str | None = None,
        chat_id: int | None = None,
        limit: int = 20,
    ) -> list[PaperTradeLog]:
        query = self.db.query(PaperTradeLog)

        if symbol is not None:
            query = query.filter(PaperTradeLog.symbol == symbol)

        if chat_id is not None:
            query = query.filter(PaperTradeLog.chat_id == chat_id)

        return query.order_by(PaperTradeLog.created_at.desc()).limit(limit).all()
