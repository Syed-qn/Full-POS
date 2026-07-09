"""category5 payments full

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "l5m6n7o8p9q0"
down_revision = "k4l5m6n7o8p9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "payment_transactions",
        "tender_type",
        existing_type=sa.String(length=16),
        type_=sa.String(length=24),
        existing_nullable=False,
    )
    op.add_column(
        "payment_transactions",
        sa.Column("channel", sa.String(24), server_default="till", nullable=False),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("reference_meta", sa.String(256), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("wallet_session_id", sa.String(128), nullable=True),
    )

    op.add_column(
        "orders",
        sa.Column("service_charge_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column("packaging_charge_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column("manager_discount_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column("staff_discount_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column("min_order_surcharge_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
    )
    op.add_column("orders", sa.Column("payment_terms", sa.String(24), nullable=True))
    op.add_column("orders", sa.Column("room_number", sa.String(32), nullable=True))
    op.add_column("orders", sa.Column("pay_later_due_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "payment_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("amount_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "paid_transaction_id",
            sa.BigInteger(),
            sa.ForeignKey("payment_transactions.id"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(64), server_default="manager", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token", name="uq_payment_links_token"),
    )
    op.create_index("ix_payment_links_restaurant_id", "payment_links", ["restaurant_id"])
    op.create_index("ix_payment_links_order_id", "payment_links", ["order_id"])
    op.create_index("ix_payment_links_token", "payment_links", ["token"])

    op.create_table(
        "payment_settlements",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("provider", sa.String(16), server_default="stripe", nullable=False),
        sa.Column("provider_payout_id", sa.String(128), nullable=False),
        sa.Column("amount_aed", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(8), server_default="AED", nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("matched_txn_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notes", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_payment_settlements_restaurant_id", "payment_settlements", ["restaurant_id"])
    op.create_index(
        "ix_payment_settlements_provider_payout_id", "payment_settlements", ["provider_payout_id"]
    )

    op.create_table(
        "payment_settlement_lines",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "settlement_id",
            sa.BigInteger(),
            sa.ForeignKey("payment_settlements.id"),
            nullable=False,
        ),
        sa.Column("provider_charge_id", sa.String(128), nullable=False),
        sa.Column("amount_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column(
            "payment_transaction_id",
            sa.BigInteger(),
            sa.ForeignKey("payment_transactions.id"),
            nullable=True,
        ),
        sa.Column("match_status", sa.String(24), server_default="unmatched", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_payment_settlement_lines_settlement_id", "payment_settlement_lines", ["settlement_id"]
    )
    op.create_index(
        "ix_payment_settlement_lines_provider_charge_id",
        "payment_settlement_lines",
        ["provider_charge_id"],
    )

    op.create_table(
        "gift_cards",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("pin_hash", sa.String(128), nullable=False),
        sa.Column("initial_amount_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("balance_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", sa.String(64), server_default="manager", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("restaurant_id", "code", name="uq_gift_cards_restaurant_code"),
    )
    op.create_index("ix_gift_cards_restaurant_id", "gift_cards", ["restaurant_id"])
    op.create_index("ix_gift_cards_code", "gift_cards", ["code"])


def downgrade() -> None:
    op.drop_table("gift_cards")
    op.drop_table("payment_settlement_lines")
    op.drop_table("payment_settlements")
    op.drop_table("payment_links")
    op.drop_column("orders", "pay_later_due_at")
    op.drop_column("orders", "room_number")
    op.drop_column("orders", "payment_terms")
    op.drop_column("orders", "min_order_surcharge_aed")
    op.drop_column("orders", "staff_discount_aed")
    op.drop_column("orders", "manager_discount_aed")
    op.drop_column("orders", "packaging_charge_aed")
    op.drop_column("orders", "service_charge_aed")
    op.drop_column("payment_transactions", "wallet_session_id")
    op.drop_column("payment_transactions", "reference_meta")
    op.drop_column("payment_transactions", "channel")
    op.alter_column(
        "payment_transactions",
        "tender_type",
        existing_type=sa.String(length=24),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
