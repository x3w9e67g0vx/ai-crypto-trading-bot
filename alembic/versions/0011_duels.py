"""duels

Friend duels: invite until accepted, then a two-player `duel` season.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-24 04:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('duels',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('challenger_id', sa.Integer(), nullable=False),
    sa.Column('opponent_id', sa.Integer(), nullable=True),
    sa.Column('season_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('winner_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.Column('accepted_at', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['challenger_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['opponent_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ),
    sa.ForeignKeyConstraint(['winner_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('season_id')
    )
    with op.batch_alter_table('duels', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_duels_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_duels_challenger_id'), ['challenger_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_duels_opponent_id'), ['opponent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_duels_status'), ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('duels', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_duels_status'))
        batch_op.drop_index(batch_op.f('ix_duels_opponent_id'))
        batch_op.drop_index(batch_op.f('ix_duels_challenger_id'))
        batch_op.drop_index(batch_op.f('ix_duels_id'))
    op.drop_table('duels')
