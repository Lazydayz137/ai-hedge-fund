"""Initial database schema

Revision ID: 001
Revises:
Create Date: 2025-11-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables for AI Hedge Fund production trading."""

    # Create portfolios table
    op.create_table(
        'portfolios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('initial_cash', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('current_cash', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('margin_requirement', sa.Numeric(precision=5, scale=4), server_default='0', nullable=True),
        sa.Column('margin_used', sa.Numeric(precision=15, scale=2), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_portfolios_id'), 'portfolios', ['id'], unique=False)

    # Create positions table
    op.create_table(
        'positions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('portfolio_id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(length=10), nullable=False),
        sa.Column('long_shares', sa.Integer(), server_default='0', nullable=True),
        sa.Column('short_shares', sa.Integer(), server_default='0', nullable=True),
        sa.Column('long_cost_basis', sa.Numeric(precision=15, scale=4), server_default='0', nullable=True),
        sa.Column('short_cost_basis', sa.Numeric(precision=15, scale=4), server_default='0', nullable=True),
        sa.Column('short_margin_used', sa.Numeric(precision=15, scale=2), server_default='0', nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('portfolio_id', 'ticker', name='uq_portfolio_ticker')
    )
    op.create_index(op.f('ix_positions_id'), 'positions', ['id'], unique=False)
    op.create_index(op.f('ix_positions_ticker'), 'positions', ['ticker'], unique=False)

    # Create decisions table
    op.create_table(
        'decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('portfolio_id', sa.Integer(), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('decision_date', sa.Date(), nullable=False),
        sa.Column('tickers', postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column('model_name', sa.String(length=50), nullable=True),
        sa.Column('model_provider', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_decisions_id'), 'decisions', ['id'], unique=False)
    op.create_index('idx_decisions_run_id', 'decisions', ['run_id'], unique=False)

    # Create trades table
    op.create_table(
        'trades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('portfolio_id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(length=10), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('price', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('total_value', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('commission', sa.Numeric(precision=10, scale=2), server_default='0', nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=False),
        sa.Column('decision_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_trades_id'), 'trades', ['id'], unique=False)
    op.create_index('idx_trades_portfolio_ticker', 'trades', ['portfolio_id', 'ticker'], unique=False)
    op.create_index('idx_trades_executed_at', 'trades', ['executed_at'], unique=False)

    # Create agent_signals table
    op.create_table(
        'agent_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('decision_id', sa.Integer(), nullable=False),
        sa.Column('agent_name', sa.String(length=100), nullable=False),
        sa.Column('ticker', sa.String(length=10), nullable=False),
        sa.Column('signal', sa.String(length=20), nullable=False),
        sa.Column('confidence', sa.Integer(), nullable=False),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('execution_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('confidence >= 0 AND confidence <= 100', name='agent_signals_confidence_check'),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_signals_id'), 'agent_signals', ['id'], unique=False)
    op.create_index('idx_agent_signals_decision', 'agent_signals', ['decision_id'], unique=False)

    # Create portfolio_decisions table
    op.create_table(
        'portfolio_decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('decision_id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(length=10), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portfolio_decisions_id'), 'portfolio_decisions', ['id'], unique=False)

    # Create realized_gains table
    op.create_table(
        'realized_gains',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('portfolio_id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(length=10), nullable=False),
        sa.Column('position_type', sa.String(length=10), nullable=False),
        sa.Column('realized_gain', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trade_id'], ['trades.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_realized_gains_id'), 'realized_gains', ['id'], unique=False)

    # Create performance_snapshots table
    op.create_table(
        'performance_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('portfolio_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('total_value', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('cash', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('long_value', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('short_value', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('realized_gains', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('unrealized_gains', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('portfolio_id', 'snapshot_date', name='uq_portfolio_snapshot_date')
    )
    op.create_index(op.f('ix_performance_snapshots_id'), 'performance_snapshots', ['id'], unique=False)
    op.create_index('idx_performance_date', 'performance_snapshots', ['portfolio_id', 'snapshot_date'], unique=False)

    # Create system_logs table
    op.create_table(
        'system_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('component', sa.String(length=100), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_system_logs_id'), 'system_logs', ['id'], unique=False)
    op.create_index('idx_logs_created', 'system_logs', ['created_at'], unique=False)
    op.create_index('idx_logs_level', 'system_logs', ['level'], unique=False)

    # Create settings table
    op.create_table(
        'settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('settings')
    op.drop_index('idx_logs_level', table_name='system_logs')
    op.drop_index('idx_logs_created', table_name='system_logs')
    op.drop_index(op.f('ix_system_logs_id'), table_name='system_logs')
    op.drop_table('system_logs')
    op.drop_index('idx_performance_date', table_name='performance_snapshots')
    op.drop_index(op.f('ix_performance_snapshots_id'), table_name='performance_snapshots')
    op.drop_table('performance_snapshots')
    op.drop_index(op.f('ix_realized_gains_id'), table_name='realized_gains')
    op.drop_table('realized_gains')
    op.drop_index(op.f('ix_portfolio_decisions_id'), table_name='portfolio_decisions')
    op.drop_table('portfolio_decisions')
    op.drop_index('idx_agent_signals_decision', table_name='agent_signals')
    op.drop_index(op.f('ix_agent_signals_id'), table_name='agent_signals')
    op.drop_table('agent_signals')
    op.drop_index('idx_trades_executed_at', table_name='trades')
    op.drop_index('idx_trades_portfolio_ticker', table_name='trades')
    op.drop_index(op.f('ix_trades_id'), table_name='trades')
    op.drop_table('trades')
    op.drop_index('idx_decisions_run_id', table_name='decisions')
    op.drop_index(op.f('ix_decisions_id'), table_name='decisions')
    op.drop_table('decisions')
    op.drop_index(op.f('ix_positions_ticker'), table_name='positions')
    op.drop_index(op.f('ix_positions_id'), table_name='positions')
    op.drop_table('positions')
    op.drop_index(op.f('ix_portfolios_id'), table_name='portfolios')
    op.drop_table('portfolios')
