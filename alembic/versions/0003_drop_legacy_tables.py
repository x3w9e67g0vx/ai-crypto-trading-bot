"""drop legacy tables

Tables of the pre-game bot (signals, paper trading, subscriptions, chat
settings, strategy profiles). Dropped only when present; nothing reads them.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28 11:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_TABLES = (
    'paper_trade_logs',
    'strategy_profiles',
    'telegram_chat_settings',
    'telegram_subscriptions',
    'portfolio_state',
    'trades',
    'signals',
)


def upgrade() -> None:
    """Upgrade schema."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name in LEGACY_TABLES:
        if name in existing:
            op.drop_table(name)


def downgrade() -> None:
    """Downgrade schema. The legacy data is gone; the tables are not recreated."""
