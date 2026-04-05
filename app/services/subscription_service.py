from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.db.models import TelegramSubscription


class SubscriptionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def subscribe(self, chat_id: int, symbol: str) -> dict[str, object]:
        existing = (
            self.db.query(TelegramSubscription)
            .filter(
                TelegramSubscription.chat_id == chat_id,
                TelegramSubscription.symbol == symbol,
            )
            .first()
        )

        if existing:
            return {
                "status": "ok",
                "message": "Already subscribed",
                "chat_id": chat_id,
                "symbol": symbol,
            }

        sub = TelegramSubscription(
            chat_id=chat_id,
            symbol=symbol,
            created_at=int(time.time() * 1000),
        )

        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        return {
            "status": "ok",
            "message": "Subscribed",
            "chat_id": chat_id,
            "symbol": symbol,
            "subscription_id": sub.id,
        }

    def unsubscribe(self, chat_id: int, symbol: str) -> dict[str, object]:
        sub = (
            self.db.query(TelegramSubscription)
            .filter(
                TelegramSubscription.chat_id == chat_id,
                TelegramSubscription.symbol == symbol,
            )
            .first()
        )

        if sub is None:
            return {
                "status": "ok",
                "message": "Subscription not found",
                "chat_id": chat_id,
                "symbol": symbol,
            }

        self.db.delete(sub)
        self.db.commit()

        return {
            "status": "ok",
            "message": "Unsubscribed",
            "chat_id": chat_id,
            "symbol": symbol,
        }

    def get_symbols_for_chat(self, chat_id: int) -> list[str]:
        rows = (
            self.db.query(TelegramSubscription)
            .filter(TelegramSubscription.chat_id == chat_id)
            .order_by(TelegramSubscription.symbol.asc())
            .all()
        )

        return [row.symbol for row in rows]

    def get_chat_ids_for_symbol(self, symbol: str) -> list[int]:
        rows = (
            self.db.query(TelegramSubscription)
            .filter(TelegramSubscription.symbol == symbol)
            .all()
        )

        return [int(row.chat_id) for row in rows]

    def get_all_for_chat(self, chat_id: int) -> dict[str, object]:
        symbols = self.get_symbols_for_chat(chat_id)

        return {
            "chat_id": chat_id,
            "count": len(symbols),
            "symbols": symbols,
        }

    def get_all_chat_ids(self) -> list[int]:
        rows = self.db.query(TelegramSubscription.chat_id).distinct().all()
        return [int(row[0]) for row in rows]
