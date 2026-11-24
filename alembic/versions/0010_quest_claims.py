"""quest claims

Season quests a portfolio finished and got XP for.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-24 03:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('quest_claims',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id', 'code', name='uq_quest_claim')
    )
    with op.batch_alter_table('quest_claims', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_quest_claims_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_quest_claims_portfolio_id'), ['portfolio_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('quest_claims', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quest_claims_portfolio_id'))
        batch_op.drop_index(batch_op.f('ix_quest_claims_id'))
    op.drop_table('quest_claims')
