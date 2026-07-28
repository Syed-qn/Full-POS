"""stock request quantity

Revision ID: 6b1c4a90d2e7
Revises: 3ef04e588fec
Create Date: 2026-07-29 05:10:00.000000

Hand-written, same reason as 3ef04e588fec: autogenerate on this database also
proposes ~40 tables of pre-existing drift that has nothing to do with stock
transfers.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b1c4a90d2e7'
down_revision: Union[str, Sequence[str], None] = '3ef04e588fec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # What was asked for, when the movement started as a request. Nullable
    # because a plain dispatch was never requested by anyone, and because
    # every row that already exists predates requests entirely.
    op.add_column(
        'stock_transfer_lines',
        sa.Column('qty_requested', sa.Numeric(precision=10, scale=3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('stock_transfer_lines', 'qty_requested')
