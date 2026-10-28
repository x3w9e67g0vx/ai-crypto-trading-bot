"""lesson progress

Lessons a player has passed; XP for them is granted once per lesson.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('lesson_progress',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('lesson_id', sa.String(), nullable=False),
    sa.Column('completed_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('player_id', 'lesson_id', name='uq_lesson_progress')
    )
    with op.batch_alter_table('lesson_progress', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lesson_progress_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lesson_progress_player_id'), ['player_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('lesson_progress', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lesson_progress_player_id'))
        batch_op.drop_index(batch_op.f('ix_lesson_progress_id'))

    op.drop_table('lesson_progress')
