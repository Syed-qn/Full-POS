"""dashboard_perf_indexes_and_usual_order_time

Revision ID: n7g8h9i0j1k2
Revises: q7r8s9t0u1v2
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = "n7g8h9i0j1k2"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("usual_order_time", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_orders_restaurant_created_at",
        "orders",
        ["restaurant_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_restaurant_created_at", table_name="orders")
    op.drop_column("customers", "usual_order_time")