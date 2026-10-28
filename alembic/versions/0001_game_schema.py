"""game schema

Clean VEYDRANOX schema. candles, indicators and model_training_runs survive
from the pre-game database: they are created only when missing, so existing
candle history is carried over. Legacy bot tables are not managed here.

Revision ID: 0001
Revises:
Create Date: 2026-10-28 09:53:50.183822

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'candles' not in existing:
        op.create_table('candles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('timeframe', sa.String(), nullable=False),
        sa.Column('timestamp', sa.BigInteger(), nullable=False),
        sa.Column('open', sa.Float(), nullable=False),
        sa.Column('high', sa.Float(), nullable=False),
        sa.Column('low', sa.Float(), nullable=False),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('volume', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'timeframe', 'timestamp', name='uq_candle_symbol_timeframe_timestamp')
        )
        with op.batch_alter_table('candles', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_candles_id'), ['id'], unique=False)
            batch_op.create_index(batch_op.f('ix_candles_symbol'), ['symbol'], unique=False)
            batch_op.create_index(batch_op.f('ix_candles_timeframe'), ['timeframe'], unique=False)
            batch_op.create_index(batch_op.f('ix_candles_timestamp'), ['timestamp'], unique=False)

    if 'model_training_runs' not in existing:
        op.create_table('model_training_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('model_type', sa.String(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('timeframe', sa.String(), nullable=False),
        sa.Column('rows', sa.Integer(), nullable=False),
        sa.Column('train_rows', sa.Integer(), nullable=False),
        sa.Column('test_rows', sa.Integer(), nullable=False),
        sa.Column('lag_periods', sa.Integer(), nullable=False),
        sa.Column('future_steps', sa.Integer(), nullable=False),
        sa.Column('accuracy', sa.Float(), nullable=True),
        sa.Column('precision', sa.Float(), nullable=True),
        sa.Column('recall', sa.Float(), nullable=True),
        sa.Column('model_path', sa.String(), nullable=True),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('model_training_runs', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_model_training_runs_created_at'), ['created_at'], unique=False)
            batch_op.create_index(batch_op.f('ix_model_training_runs_id'), ['id'], unique=False)
            batch_op.create_index(batch_op.f('ix_model_training_runs_model_type'), ['model_type'], unique=False)
            batch_op.create_index(batch_op.f('ix_model_training_runs_symbol'), ['symbol'], unique=False)
            batch_op.create_index(batch_op.f('ix_model_training_runs_timeframe'), ['timeframe'], unique=False)

    op.create_table('players',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('telegram_id', sa.BigInteger(), nullable=True),
    sa.Column('nickname', sa.String(), nullable=False),
    sa.Column('nickname_set', sa.Boolean(), nullable=False),
    sa.Column('language', sa.String(), nullable=False),
    sa.Column('is_ai', sa.Boolean(), nullable=False),
    sa.Column('ai_key', sa.String(), nullable=True),
    sa.Column('league_tier', sa.String(), nullable=False),
    sa.Column('xp', sa.Integer(), nullable=False),
    sa.Column('is_banned', sa.Boolean(), nullable=False),
    sa.Column('is_pro_until', sa.BigInteger(), nullable=True),
    sa.Column('referred_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['referred_by_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ai_key')
    )
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_players_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_players_telegram_id'), ['telegram_id'], unique=True)

    op.create_table('seasons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('starts_at', sa.BigInteger(), nullable=False),
    sa.Column('ends_at', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'starts_at', name='uq_season_kind_starts_at')
    )
    with op.batch_alter_table('seasons', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_seasons_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_seasons_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_seasons_status'), ['status'], unique=False)

    op.create_table('ai_decisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('candle_ts', sa.BigInteger(), nullable=False),
    sa.Column('probability_up', sa.Float(), nullable=False),
    sa.Column('view', sa.String(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('player_id', 'symbol', 'candle_ts', name='uq_ai_decision_candle')
    )
    with op.batch_alter_table('ai_decisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_decisions_candle_ts'), ['candle_ts'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_decisions_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_decisions_player_id'), ['player_id'], unique=False)

    op.create_table('badges',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('badges', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_badges_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_badges_player_id'), ['player_id'], unique=False)

    if 'indicators' not in existing:
        op.create_table('indicators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('candle_id', sa.Integer(), nullable=False),
        sa.Column('rsi', sa.Float(), nullable=True),
        sa.Column('ema_fast', sa.Float(), nullable=True),
        sa.Column('ema_slow', sa.Float(), nullable=True),
        sa.Column('macd', sa.Float(), nullable=True),
        sa.Column('bollinger_upper', sa.Float(), nullable=True),
        sa.Column('bollinger_lower', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['candle_id'], ['candles.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('indicators', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_indicators_candle_id'), ['candle_id'], unique=True)
            batch_op.create_index(batch_op.f('ix_indicators_id'), ['id'], unique=False)

    op.create_table('league_groups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('tier', sa.String(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('season_id', 'tier', 'number', name='uq_league_group')
    )
    with op.batch_alter_table('league_groups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_league_groups_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_league_groups_season_id'), ['season_id'], unique=False)

    op.create_table('portfolios',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('cash', sa.Float(), nullable=False),
    sa.Column('trades_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('player_id', 'season_id', name='uq_portfolio_player_season')
    )
    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portfolios_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_portfolios_player_id'), ['player_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_portfolios_season_id'), ['season_id'], unique=False)

    op.create_table('league_memberships',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('joined_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['league_groups.id'], ),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id')
    )
    with op.batch_alter_table('league_memberships', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_league_memberships_group_id'), ['group_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_league_memberships_id'), ['id'], unique=False)

    op.create_table('portfolio_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('portfolio_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portfolio_snapshots_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_portfolio_snapshots_portfolio_id'), ['portfolio_id'], unique=False)

    op.create_table('positions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('side', sa.String(), nullable=False),
    sa.Column('qty', sa.Float(), nullable=False),
    sa.Column('entry_price', sa.Float(), nullable=False),
    sa.Column('reserved', sa.Float(), nullable=False),
    sa.Column('stop_loss', sa.Float(), nullable=True),
    sa.Column('take_profit', sa.Float(), nullable=True),
    sa.Column('opened_at', sa.BigInteger(), nullable=False),
    sa.Column('closed_at', sa.BigInteger(), nullable=True),
    sa.Column('exit_price', sa.Float(), nullable=True),
    sa.Column('pnl', sa.Float(), nullable=True),
    sa.Column('close_reason', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('positions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_positions_closed_at'), ['closed_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_positions_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_positions_portfolio_id'), ['portfolio_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_positions_symbol'), ['symbol'], unique=False)
        batch_op.create_index('uq_position_open_symbol', ['portfolio_id', 'symbol'], unique=True, postgresql_where=sa.text('closed_at IS NULL'), sqlite_where=sa.text('closed_at IS NULL'))

    op.create_table('fills',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('position_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('side', sa.String(), nullable=False),
    sa.Column('qty', sa.Float(), nullable=False),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('fee', sa.Float(), nullable=False),
    sa.Column('is_user', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ),
    sa.ForeignKeyConstraint(['position_id'], ['positions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('fills', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fills_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_fills_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_fills_portfolio_id'), ['portfolio_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_fills_position_id'), ['position_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema. Kept tables (candles, indicators, model_training_runs) stay."""
    with op.batch_alter_table('fills', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fills_position_id'))
        batch_op.drop_index(batch_op.f('ix_fills_portfolio_id'))
        batch_op.drop_index(batch_op.f('ix_fills_id'))
        batch_op.drop_index(batch_op.f('ix_fills_created_at'))

    op.drop_table('fills')
    with op.batch_alter_table('positions', schema=None) as batch_op:
        batch_op.drop_index('uq_position_open_symbol', postgresql_where=sa.text('closed_at IS NULL'), sqlite_where=sa.text('closed_at IS NULL'))
        batch_op.drop_index(batch_op.f('ix_positions_symbol'))
        batch_op.drop_index(batch_op.f('ix_positions_portfolio_id'))
        batch_op.drop_index(batch_op.f('ix_positions_id'))
        batch_op.drop_index(batch_op.f('ix_positions_closed_at'))

    op.drop_table('positions')
    with op.batch_alter_table('portfolio_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portfolio_snapshots_portfolio_id'))
        batch_op.drop_index(batch_op.f('ix_portfolio_snapshots_id'))

    op.drop_table('portfolio_snapshots')
    with op.batch_alter_table('league_memberships', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_league_memberships_id'))
        batch_op.drop_index(batch_op.f('ix_league_memberships_group_id'))

    op.drop_table('league_memberships')
    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portfolios_season_id'))
        batch_op.drop_index(batch_op.f('ix_portfolios_player_id'))
        batch_op.drop_index(batch_op.f('ix_portfolios_id'))

    op.drop_table('portfolios')
    with op.batch_alter_table('league_groups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_league_groups_season_id'))
        batch_op.drop_index(batch_op.f('ix_league_groups_id'))

    op.drop_table('league_groups')
    with op.batch_alter_table('badges', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_badges_player_id'))
        batch_op.drop_index(batch_op.f('ix_badges_id'))

    op.drop_table('badges')
    with op.batch_alter_table('ai_decisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_decisions_player_id'))
        batch_op.drop_index(batch_op.f('ix_ai_decisions_id'))
        batch_op.drop_index(batch_op.f('ix_ai_decisions_candle_ts'))

    op.drop_table('ai_decisions')
    with op.batch_alter_table('seasons', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_seasons_status'))
        batch_op.drop_index(batch_op.f('ix_seasons_kind'))
        batch_op.drop_index(batch_op.f('ix_seasons_id'))

    op.drop_table('seasons')
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_players_telegram_id'))
        batch_op.drop_index(batch_op.f('ix_players_id'))

    op.drop_table('players')
