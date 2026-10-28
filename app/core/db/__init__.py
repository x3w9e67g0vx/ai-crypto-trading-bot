from app.core.db.models import (
    Candle,
    Indicator,
    ModelTrainingRun,
    PortfolioState,
    Signal,
    TelegramSubscription,
    Trade,
)
import app.game.models  # noqa: F401,E402  registers game tables on Base

# Old bot tables: kept until the bot is rewritten (phase 4), not managed by Alembic.
LEGACY_TABLES = frozenset(
    {
        "signals",
        "trades",
        "portfolio_state",
        "telegram_subscriptions",
        "telegram_chat_settings",
        "strategy_profiles",
        "paper_trade_logs",
    }
)

__all__ = [
    "Candle",
    "Indicator",
    "Signal",
    "Trade",
    "PortfolioState",
    "ModelTrainingRun",
    "TelegramSubscription",
]
