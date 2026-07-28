"""count reason codes and costed variance

Revision ID: ac5040244721
Revises: b9c0d1e2f3a4
Create Date: 2026-07-28 23:13:36.418041

Hand-trimmed. Autogenerate also proposed ~40 tables of PRE-EXISTING drift —
INTEGER to BigInteger widening, TIMESTAMP to DateTime, index rebuilds, and NOT
NULL on tickets.evidence and catalog_products.raw, which would fail outright if
any existing row holds a null. None of that belongs in a migration about stock
counts, so only the five new columns are kept here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ac5040244721'
down_revision: Union[str, Sequence[str], None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-ingredient count tolerance; NULL means fall back to the default.
    op.add_column(
        'ingredients',
        sa.Column('count_variance_threshold_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    )

    # Why the count differed, and what the difference cost.
    op.add_column('stock_count_logs', sa.Column('reason_code', sa.String(length=24), nullable=True))
    op.add_column('stock_count_logs', sa.Column('reason', sa.String(length=256), nullable=True))
    op.add_column(
        'stock_count_logs',
        sa.Column(
            'variance_value_aed',
            sa.Numeric(precision=12, scale=2),
            server_default='0.00',
            nullable=False,
        ),
    )
    op.add_column(
        'stock_count_logs',
        sa.Column('reviewed', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('stock_count_logs', 'reviewed')
    op.drop_column('stock_count_logs', 'variance_value_aed')
    op.drop_column('stock_count_logs', 'reason')
    op.drop_column('stock_count_logs', 'reason_code')
    op.drop_column('ingredients', 'count_variance_threshold_pct')
