"""cash drawer tables

Revision ID: 040d78934696
Revises: f994402c77a2
Create Date: 2026-07-07 08:26:12.391561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '040d78934696'
down_revision: Union[str, Sequence[str], None] = 'f994402c77a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cash_drawer_sessions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('opened_by', sa.String(length=64), nullable=False),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('opening_float_aed', sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column('closed_by', sa.String(length=64), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closing_count_aed', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('variance_aed', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_cash_drawer_sessions_restaurant_id'), 'cash_drawer_sessions', ['restaurant_id'], unique=False
    )

    op.create_table(
        'cash_drawer_events',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('session_id', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('amount_aed', sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column('reason', sa.String(length=256), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['session_id'], ['cash_drawer_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_cash_drawer_events_restaurant_id'), 'cash_drawer_events', ['restaurant_id'], unique=False
    )
    op.create_index(
        op.f('ix_cash_drawer_events_session_id'), 'cash_drawer_events', ['session_id'], unique=False
    )

    for tbl in ('cash_drawer_sessions', 'cash_drawer_events'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ('cash_drawer_sessions', 'cash_drawer_events'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")

    op.drop_index(op.f('ix_cash_drawer_events_session_id'), table_name='cash_drawer_events')
    op.drop_index(op.f('ix_cash_drawer_events_restaurant_id'), table_name='cash_drawer_events')
    op.drop_table('cash_drawer_events')

    op.drop_index(op.f('ix_cash_drawer_sessions_restaurant_id'), table_name='cash_drawer_sessions')
    op.drop_table('cash_drawer_sessions')
