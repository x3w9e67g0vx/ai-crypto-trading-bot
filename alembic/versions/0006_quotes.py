"""quotes

Latest bid/ask per symbol, shared by the price worker with the other processes.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('quotes',
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('bid', sa.Float(), nullable=False),
    sa.Column('ask', sa.Float(), nullable=False),
    sa.Column('ts', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('symbol')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('quotes')
