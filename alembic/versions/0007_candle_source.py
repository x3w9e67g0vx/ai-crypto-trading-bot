"""candle source

Where a candle came from: binance, or bybit while Binance was down (charts only).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28 22:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('candles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(), server_default='binance', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('candles', schema=None) as batch_op:
        batch_op.drop_column('source')
