"""wallet, tickets, coupon v2 + order wallet_applied

Adds:
  * wallet_accounts, wallet_entries   — ledger-based customer store credit
  * tickets                           — complaint tickets (human-resolved)
  * coupon_redemptions                — append-only redemption ledger
  * coupons.*                         — campaign columns; code unique per tenant
  * orders.wallet_applied_aed         — wallet credit applied to an order

All new TimestampMixin tables get the standard BEFORE UPDATE trg_*_updated_at
trigger (set_updated_at() exists from an earlier migration).

Revision ID: f1a2b3c4d5e6
Revises: e2b3d4f5a6c7
Create Date: 2026-06-29
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e2b3d4f5a6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── wallet_accounts ──────────────────────────────────────────────────────
    op.create_table(
        "wallet_accounts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "customer_id", name="uq_wallet_accounts_restaurant_customer"),
    )
    op.create_index("ix_wallet_accounts_restaurant_id", "wallet_accounts", ["restaurant_id"])
    op.create_index("ix_wallet_accounts_customer_id", "wallet_accounts", ["customer_id"])
    op.create_index("ix_wallet_accounts_status", "wallet_accounts", ["status"])
    op.execute(
        "CREATE TRIGGER trg_wallet_accounts_updated_at BEFORE UPDATE ON wallet_accounts "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # ── wallet_entries ───────────────────────────────────────────────────────
    op.create_table(
        "wallet_entries",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_aed", sa.Numeric(10, 2), nullable=False),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="posted"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("ticket_id", sa.BigInteger(), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("reverses_entry_id", sa.BigInteger(), nullable=True),
        sa.Column("reason_note", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["wallet_accounts.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_wallet_entries_idempotency_key"),
    )
    op.create_index("ix_wallet_entries_account_id", "wallet_entries", ["account_id"])
    op.create_index("ix_wallet_entries_restaurant_id", "wallet_entries", ["restaurant_id"])
    op.create_index("ix_wallet_entries_type", "wallet_entries", ["type"])
    op.create_index("ix_wallet_entries_status", "wallet_entries", ["status"])
    op.create_index("ix_wallet_entries_account_status", "wallet_entries", ["account_id", "status"])
    op.create_index("ix_wallet_entries_order", "wallet_entries", ["account_id", "order_id"])
    op.execute(
        "CREATE TRIGGER trg_wallet_entries_updated_at BEFORE UPDATE ON wallet_entries "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # ── tickets ──────────────────────────────────────────────────────────────
    op.create_table(
        "tickets",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("source_message", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("category", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("assigned_to", sa.String(length=64), nullable=True),
        sa.Column("resolution_action", sa.String(length=24), nullable=False, server_default="none"),
        sa.Column("resolution_amount_aed", sa.Numeric(8, 2), nullable=True),
        sa.Column("replacement_order_id", sa.BigInteger(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tickets_restaurant_id", "tickets", ["restaurant_id"])
    op.create_index("ix_tickets_customer_id", "tickets", ["customer_id"])
    op.create_index("ix_tickets_order_id", "tickets", ["order_id"])
    op.create_index("ix_tickets_status", "tickets", ["status"])
    op.create_index("ix_tickets_restaurant_status", "tickets", ["restaurant_id", "status"])
    op.execute(
        "CREATE TRIGGER trg_tickets_updated_at BEFORE UPDATE ON tickets "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # ── coupon_redemptions ───────────────────────────────────────────────────
    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("coupon_id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("discount_applied_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_coupon_redemptions_idempotency_key"),
    )
    op.create_index("ix_coupon_redemptions_coupon_id", "coupon_redemptions", ["coupon_id"])
    op.create_index("ix_coupon_redemptions_restaurant_id", "coupon_redemptions", ["restaurant_id"])
    op.create_index("ix_coupon_redemptions_customer_id", "coupon_redemptions", ["customer_id"])
    op.create_index("ix_coupon_redemptions_order_id", "coupon_redemptions", ["order_id"])
    op.execute(
        "CREATE TRIGGER trg_coupon_redemptions_updated_at BEFORE UPDATE ON coupon_redemptions "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # ── coupons: campaign columns + per-tenant unique code ───────────────────
    op.add_column("coupons", sa.Column("kind", sa.String(length=12), nullable=False, server_default="single_use"))
    op.add_column("coupons", sa.Column("discount_type", sa.String(length=8), nullable=False, server_default="fixed"))
    op.add_column("coupons", sa.Column("percent", sa.Numeric(5, 2), nullable=True))
    op.add_column("coupons", sa.Column("max_discount_aed", sa.Numeric(8, 2), nullable=True))
    op.add_column("coupons", sa.Column("min_order_aed", sa.Numeric(8, 2), nullable=False, server_default="0"))
    op.add_column("coupons", sa.Column("applies_to", sa.String(length=16), nullable=False, server_default="whole_order"))
    op.add_column("coupons", sa.Column("per_customer_limit", sa.Integer(), nullable=True))
    op.add_column("coupons", sa.Column("total_redemption_limit", sa.Integer(), nullable=True))
    op.add_column("coupons", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("coupons", sa.Column("created_by", sa.String(length=64), nullable=True))
    # Campaign coupons have no customer/order/fixed-amount at creation.
    op.alter_column("coupons", "customer_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("coupons", "order_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("coupons", "discount_aed", existing_type=sa.Numeric(8, 2), nullable=True)
    # Swap global-unique code -> per-tenant unique.
    op.drop_index("ix_coupons_code", table_name="coupons")
    op.create_index("ix_coupons_code", "coupons", ["code"], unique=False)
    op.create_unique_constraint("uq_coupons_restaurant_code", "coupons", ["restaurant_id", "code"])

    # ── orders: wallet credit applied ────────────────────────────────────────
    op.add_column(
        "orders",
        sa.Column("wallet_applied_aed", sa.Numeric(8, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("orders", "wallet_applied_aed")

    op.drop_constraint("uq_coupons_restaurant_code", "coupons", type_="unique")
    op.drop_index("ix_coupons_code", table_name="coupons")
    op.create_index("ix_coupons_code", "coupons", ["code"], unique=True)
    op.alter_column("coupons", "discount_aed", existing_type=sa.Numeric(8, 2), nullable=False)
    op.alter_column("coupons", "order_id", existing_type=sa.BigInteger(), nullable=False)
    op.alter_column("coupons", "customer_id", existing_type=sa.BigInteger(), nullable=False)
    for col in (
        "created_by", "valid_from", "total_redemption_limit", "per_customer_limit",
        "applies_to", "min_order_aed", "max_discount_aed", "percent", "discount_type", "kind",
    ):
        op.drop_column("coupons", col)

    for t in ("coupon_redemptions", "tickets", "wallet_entries", "wallet_accounts"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{t}_updated_at ON {t};")
        op.drop_table(t)
