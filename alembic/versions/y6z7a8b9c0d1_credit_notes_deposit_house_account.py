"""credit_notes table; orders.deposit_paid_aed; customers house account fields

Adds:
- credit_notes: formal credit-note artifacts issued against a refunded
  PaymentTransaction (per-tenant sequential credit_note_number, e.g. CN-1-0001).
- orders.deposit_paid_aed: running total of deposit/advance PaymentTransaction
  rows charged before a (typically scheduled) order is fully prepared.
- customers.house_account_enabled / house_account_balance_aed: run-a-tab
  billing for VIP/corporate customers — a plain running balance the customer
  owes the restaurant (not an append-only ledger like the wallet), plus an
  optional per-customer credit limit.

Revision ID: y6z7a8b9c0d1
Revises: 5c8c8d3b2c85
Create Date: 2026-07-08
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "y6z7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "5c8c8d3b2c85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "deposit_paid_aed",
            sa.Numeric(8, 2),
            server_default="0.00",
            nullable=False,
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "house_account_enabled",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "house_account_balance_aed",
            sa.Numeric(10, 2),
            server_default="0.00",
            nullable=False,
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "house_account_credit_limit_aed",
            sa.Numeric(10, 2),
            nullable=True,
        ),
    )

    op.create_table(
        "credit_notes",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.Column("credit_note_number", sa.String(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["payment_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "restaurant_id", "credit_note_number", name="uq_credit_notes_restaurant_number"
        ),
    )
    op.create_index(
        "ix_credit_notes_restaurant_id", "credit_notes", ["restaurant_id"]
    )
    op.create_index(
        "ix_credit_notes_order_id", "credit_notes", ["order_id"]
    )
    op.create_index(
        "ix_credit_notes_transaction_id", "credit_notes", ["transaction_id"]
    )
    op.create_index(
        "ix_credit_notes_credit_note_number", "credit_notes", ["credit_note_number"]
    )
    op.execute(
        "CREATE TRIGGER trg_credit_notes_updated_at "
        "BEFORE UPDATE ON credit_notes "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_credit_notes_updated_at ON credit_notes;")
    op.drop_index("ix_credit_notes_credit_note_number", table_name="credit_notes")
    op.drop_index("ix_credit_notes_transaction_id", table_name="credit_notes")
    op.drop_index("ix_credit_notes_order_id", table_name="credit_notes")
    op.drop_index("ix_credit_notes_restaurant_id", table_name="credit_notes")
    op.drop_table("credit_notes")

    op.drop_column("customers", "house_account_credit_limit_aed")
    op.drop_column("customers", "house_account_balance_aed")
    op.drop_column("customers", "house_account_enabled")
    op.drop_column("orders", "deposit_paid_aed")
