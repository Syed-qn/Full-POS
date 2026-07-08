"""add order_items.seat_number (split-by-seat billing for dine-in)

Nullable seat assignment on each line item so a table's bill can be split
"by seat" (in addition to the existing split-by-item). Null = unassigned /
shared item (e.g. a shared appetizer). Meaningful only on orders bound to a
table (Order.table_id), not enforced at the DB level.

Revision ID: u2v3w4x5y6z7
Revises: 122f2270dfbc
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "u2v3w4x5y6z7"
down_revision = "122f2270dfbc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("seat_number", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "seat_number")
