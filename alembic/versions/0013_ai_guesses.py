"""ai guesses

Player bets on the next candle: price direction and the AI majority view.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-24 04:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_guesses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('candle_ts', sa.BigInteger(), nullable=False),
    sa.Column('price', sa.String(), nullable=False),
    sa.Column('view', sa.String(), nullable=False),
    sa.Column('price_correct', sa.Boolean(), nullable=True),
    sa.Column('ai_correct', sa.Boolean(), nullable=True),
    sa.Column('xp', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.Column('settled_at', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('player_id', 'symbol', 'candle_ts', name='uq_ai_guess')
    )
    with op.batch_alter_table('ai_guesses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_guesses_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_guesses_player_id'), ['player_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_guesses_settled_at'), ['settled_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_guesses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_guesses_settled_at'))
        batch_op.drop_index(batch_op.f('ix_ai_guesses_player_id'))
        batch_op.drop_index(batch_op.f('ix_ai_guesses_id'))
    op.drop_table('ai_guesses')
