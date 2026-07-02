"""order POS sync fields: pos_order_id, pos_pushed_at, pos_push_status

Revision ID: o8b9c0d1e2f3
Revises: n7a8b9c0d1e2
Create Date: 2026-07-01
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "o8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "n7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("pos_order_id", sa.String(length=64), nullable=True))
    op.add_column(
        "orders",
        sa.Column("pos_pushed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("pos_push_status", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_orders_restaurant_status_created",
        "orders",
        ["restaurant_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_restaurant_status_created", table_name="orders")
    op.drop_column("orders", "pos_push_status")
    op.drop_column("orders", "pos_pushed_at")
    op.drop_column("orders", "pos_order_id")