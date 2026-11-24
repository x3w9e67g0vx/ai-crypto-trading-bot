"""shop and llm reviews

Stars payments, equipped cosmetics on players, cached LLM trade reviews.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-24 05:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(sa.Column('frame', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('nick_color', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('ai_skin', sa.String(), nullable=True))
    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('item', sa.String(), nullable=False),
    sa.Column('stars', sa.Integer(), nullable=False),
    sa.Column('charge_id', sa.String(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('charge_id')
    )
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payments_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_player_id'), ['player_id'], unique=False)
    op.create_table('llm_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('position_id', sa.Integer(), nullable=False),
    sa.Column('language', sa.String(), nullable=False),
    sa.Column('text', sa.String(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['position_id'], ['positions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('position_id', 'language', name='uq_llm_review')
    )
    with op.batch_alter_table('llm_reviews', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_llm_reviews_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_llm_reviews_position_id'), ['position_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('llm_reviews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_reviews_position_id'))
        batch_op.drop_index(batch_op.f('ix_llm_reviews_id'))
    op.drop_table('llm_reviews')
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_player_id'))
        batch_op.drop_index(batch_op.f('ix_payments_id'))
    op.drop_table('payments')
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('ai_skin')
        batch_op.drop_column('nick_color')
        batch_op.drop_column('frame')
