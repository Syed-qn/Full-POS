"""partner_webhook_deliveries: outbound POS webhook queue

Revision ID: n7a8b9c0d1e2
Revises: m6f7a8b9c0d1
Create Date: 2026-07-01
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "n7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "m6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "partner_webhook_deliveries",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("target_url", sa.String(length=512), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_partner_webhook_deliveries_restaurant_id",
        "partner_webhook_deliveries",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_partner_webhook_deliveries_event_type",
        "partner_webhook_deliveries",
        ["event_type"],
    )
    op.create_index(
        "ix_partner_webhook_deliveries_idempotency_key",
        "partner_webhook_deliveries",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_partner_webhook_deliveries_status",
        "partner_webhook_deliveries",
        ["status"],
    )
    op.execute(
        "CREATE TRIGGER trg_partner_webhook_deliveries_updated_at "
        "BEFORE UPDATE ON partner_webhook_deliveries "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_partner_webhook_deliveries_updated_at "
        "ON partner_webhook_deliveries;"
    )
    op.drop_index("ix_partner_webhook_deliveries_status", table_name="partner_webhook_deliveries")
    op.drop_index(
        "ix_partner_webhook_deliveries_idempotency_key",
        table_name="partner_webhook_deliveries",
    )
    op.drop_index(
        "ix_partner_webhook_deliveries_event_type",
        table_name="partner_webhook_deliveries",
    )
    op.drop_index(
        "ix_partner_webhook_deliveries_restaurant_id",
        table_name="partner_webhook_deliveries",
    )
    op.drop_table("partner_webhook_deliveries")