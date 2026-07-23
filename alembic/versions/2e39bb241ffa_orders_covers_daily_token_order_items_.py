"""orders.covers/daily_token, order_items.is_takeaway/merged_from_order_id

Four columns that the ORM models declare but no migration ever created: they
were added to the dev database by hand with ALTER TABLE during development, so
everything worked locally while a database built purely from migrations — i.e.
every fresh deploy — was missing them. Symptom: any SELECT naming them 500s, so
GET /api/v1/orders and GET /api/v1/tables failed on a freshly migrated
production database even with zero rows in the table.

IF NOT EXISTS on each add, and a guarded index create, so this is safe to run
against a database that was hand-patched the same way (the dev one).

Revision ID: 2e39bb241ffa
Revises: e1c23230b540
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "2e39bb241ffa"
down_revision: Union[str, Sequence[str], None] = "e1c23230b540"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Dine-in party size; null for non-dine-in orders.
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS covers INTEGER")
    # Short per-day ticket number (Asia/Dubai day). Distinct from order_number,
    # which is the permanent invoice id. Null for legacy rows.
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS daily_token INTEGER")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_daily_token ON orders (daily_token)"
    )
    # A dine-in line the guest wants boxed: same order, same bill, but the
    # kitchen must pack it.
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS is_takeaway "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    # Where this line came from when a table merge moved it, so "undo merge"
    # can pop exactly these lines back. Deliberately no FK: the source order may
    # be archived independently.
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS merged_from_order_id BIGINT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_items_merged_from_order_id "
        "ON order_items (merged_from_order_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_order_items_merged_from_order_id")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS merged_from_order_id")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS is_takeaway")
    op.execute("DROP INDEX IF EXISTS ix_orders_daily_token")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS daily_token")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS covers")
