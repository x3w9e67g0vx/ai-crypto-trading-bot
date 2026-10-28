"""bot tables

Notification flags and league rank watermark, notifications, private chat
leagues and analytics events.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 10:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOTIFY_COLUMNS = ('notify_overtaken', 'notify_ai_open', 'notify_season_end')


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('players', schema=None) as batch_op:
        for name in NOTIFY_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text('true')))

    with op.batch_alter_table('league_memberships', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_rank', sa.Integer(), nullable=True))

    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('player_id', 'kind', 'key', name='uq_notification_event')
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_player_id'), ['player_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_created_at'), ['created_at'], unique=False)

    op.create_table('chat_leagues',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('chat_leagues', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_leagues_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_leagues_chat_id'), ['chat_id'], unique=True)

    op.create_table('chat_league_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('league_id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('joined_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['league_id'], ['chat_leagues.id'], ),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('league_id', 'player_id', name='uq_chat_league_member')
    )
    with op.batch_alter_table('chat_league_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_league_members_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_league_members_league_id'), ['league_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_league_members_player_id'), ['player_id'], unique=False)

    op.create_table('events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_events_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_player_id'), ['player_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_created_at'), ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('events')
    op.drop_table('chat_league_members')
    op.drop_table('chat_leagues')
    op.drop_table('notifications')
    with op.batch_alter_table('league_memberships', schema=None) as batch_op:
        batch_op.drop_column('last_rank')
    with op.batch_alter_table('players', schema=None) as batch_op:
        for name in NOTIFY_COLUMNS:
            batch_op.drop_column(name)
