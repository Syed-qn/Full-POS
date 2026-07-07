"""customer loyalty points (unused — superseded by app.loyalty's tier/cashback
system, kept only so the migration chain matches what's already applied to
existing databases; do not wire a new model attribute to this column)

Revision ID: 23fe040d7fe8
Revises: b4d5c3292884
Create Date: 2026-07-07 17:41:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '23fe040d7fe8'
down_revision: Union[str, Sequence[str], None] = 'b4d5c3292884'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'customers', sa.Column('loyalty_points', sa.Integer(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    op.drop_column('customers', 'loyalty_points')
