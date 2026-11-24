"""daily puzzle

One chart puzzle per UTC day and the players' answers to it.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24 03:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('daily_puzzles',
    sa.Column('day', sa.String(), nullable=False),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('cut_ts', sa.BigInteger(), nullable=False),
    sa.Column('answer', sa.String(), nullable=False),
    sa.Column('move_pct', sa.Float(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('day')
    )
    op.create_table('puzzle_answers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.String(), nullable=False),
    sa.Column('choice', sa.String(), nullable=False),
    sa.Column('correct', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['day'], ['daily_puzzles.day'], ),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('player_id', 'day', name='uq_puzzle_answer')
    )
    with op.batch_alter_table('puzzle_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_puzzle_answers_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_puzzle_answers_player_id'), ['player_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('puzzle_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_puzzle_answers_player_id'))
        batch_op.drop_index(batch_op.f('ix_puzzle_answers_id'))
    op.drop_table('puzzle_answers')
    op.drop_table('daily_puzzles')
