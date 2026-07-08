"""add orders.delivery_failure_reason (failed-delivery reason on undeliverable orders)

Manager can record why a delivery attempt failed (app.dispatch.delivery.
mark_delivery_failed) when transitioning an order into the FSM's existing
`undeliverable` terminal status (spec §3 — no new status invented).

Revision ID: w4x5y6z7a8b9
Revises: 122f2270dfbc
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "w4x5y6z7a8b9"
down_revision = "122f2270dfbc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("delivery_failure_reason", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "delivery_failure_reason")
