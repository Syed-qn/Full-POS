"""orders_unique_order_number

W8 task 3 (TX-13/F114): order numbers must be unique per tenant forever, with a
DB unique constraint as the hard backstop for the atomic advisory-lock-guarded
allocation in ``create_draft_order``. Any pre-existing duplicate
(restaurant_id, order_number) rows are disambiguated first so the constraint
can be added cleanly.

Revision ID: o8h9i0j1k2l3
Revises: n7g8h9i0j1k2
Create Date: 2026-07-01
"""
from alembic import op

revision = "o8h9i0j1k2l3"
down_revision = "n7g8h9i0j1k2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Disambiguate any pre-existing duplicates (e.g. from a dev/test DB reset,
    # TX-13) before the unique constraint can be applied — keep the earliest row's
    # order_number untouched, suffix later duplicates so no data is lost or hidden.
    op.execute(
        """
        WITH ranked AS (
            SELECT id, restaurant_id, order_number,
                   row_number() OVER (
                       PARTITION BY restaurant_id, order_number
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM orders
        )
        UPDATE orders o
        SET order_number = o.order_number || '-DUP' || ranked.rn
        FROM ranked
        WHERE o.id = ranked.id AND ranked.rn > 1
        """
    )
    op.create_unique_constraint(
        "uq_orders_restaurant_order_number", "orders", ["restaurant_id", "order_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_orders_restaurant_order_number", "orders", type_="unique")
