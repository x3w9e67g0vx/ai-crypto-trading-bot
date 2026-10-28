"""channel posts

Posts published to the channel; (kind, key) is unique so a post never repeats.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('channel_posts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'key', name='uq_channel_post')
    )
    with op.batch_alter_table('channel_posts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_channel_posts_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_channel_posts_id'), ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('channel_posts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_channel_posts_id'))
        batch_op.drop_index(batch_op.f('ix_channel_posts_created_at'))

    op.drop_table('channel_posts')
