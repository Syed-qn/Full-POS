"""add order_items.cancelled and order_items.cancelled_reason (partial line-item cancel)

Manager can cancel a single line item without voiding the whole order. Cancelled
items are excluded from order.subtotal/total (service.cancel_order_item) but kept
on the row as an audit trail rather than deleted.

Revision ID: t1u2v3w4x5y6
Revises: 03b3d42e1ef8
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = "t1u2v3w4x5y6"
down_revision = "03b3d42e1ef8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "order_items",
        sa.Column("cancelled_reason", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "cancelled_reason")
    op.drop_column("order_items", "cancelled")
