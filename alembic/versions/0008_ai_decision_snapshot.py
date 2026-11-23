"""ai decision snapshot

Thresholds, trend filter and EMAs an AI persona decided on, for the "why it entered" card.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-24 02:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ('buy_threshold', 'sell_threshold', 'trend_filter', 'ema_fast', 'ema_slow')


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('ai_decisions', schema=None) as batch_op:
        for name in COLUMNS:
            kind = sa.Boolean() if name == 'trend_filter' else sa.Float()
            batch_op.add_column(sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_decisions', schema=None) as batch_op:
        for name in reversed(COLUMNS):
            batch_op.drop_column(name)
