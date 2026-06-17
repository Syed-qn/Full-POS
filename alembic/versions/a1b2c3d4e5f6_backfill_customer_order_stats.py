"""backfill customer order stats

Recompute the denormalized customers.total_orders / total_spend /
first_order_at / last_order_at columns from the orders table. These columns
were never maintained, so existing rows are all at their creation defaults
(0 / NULL). Going forward they're kept in sync by
ordering.service.recompute_customer_stats (called from fsm.transition and
dispatch.advance_delivery); this migration fixes the historical rows.

total_orders counts non-draft orders, total_spend sums delivered orders only
(COD actually collected), and the timestamps span non-draft orders.

Revision ID: a1b2c3d4e5f6
Revises: 464f76bc2e70
Create Date: 2026-06-18 05:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '464f76bc2e70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE customers c SET
            total_orders   = COALESCE(o.cnt, 0),
            total_spend    = COALESCE(o.spend, 0),
            first_order_at = o.first_at,
            last_order_at  = o.last_at
        FROM (
            SELECT customer_id,
                COUNT(*) FILTER (WHERE status <> 'draft')                      AS cnt,
                COALESCE(SUM(total) FILTER (WHERE status = 'delivered'), 0)    AS spend,
                MIN(created_at) FILTER (WHERE status <> 'draft')              AS first_at,
                MAX(created_at) FILTER (WHERE status <> 'draft')              AS last_at
            FROM orders
            GROUP BY customer_id
        ) o
        WHERE c.id = o.customer_id;
        """
    )


def downgrade() -> None:
    # Data-only backfill — nothing to reverse.
    pass
