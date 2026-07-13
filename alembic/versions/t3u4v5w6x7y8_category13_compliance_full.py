"""category13 uae compliance full

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "t3u4v5w6x7y8"
down_revision = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("vat_rate", sa.Numeric(5, 4), server_default="0.0500", nullable=False),
    )
    op.add_column(
        "order_items",
        sa.Column("vat_amount_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column(
            "invoice_kind",
            sa.String(32),
            server_default="simplified_tax_invoice",
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "tax_pricing_mode",
            sa.String(16),
            server_default="exclusive",
            nullable=False,
        ),
    )
    op.add_column(
        "dishes",
        sa.Column("vat_rate", sa.Numeric(5, 4), nullable=True),
    )

    op.create_table(
        "refund_notes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False, index=True
        ),
        sa.Column(
            "transaction_id",
            sa.BigInteger(),
            sa.ForeignKey("payment_transactions.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("amount_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("vat_amount_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
        sa.Column("reason", sa.String(256), nullable=True),
        sa.Column("refund_note_number", sa.String(32), nullable=False, index=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "restaurant_id",
            "refund_note_number",
            name="uq_refund_notes_restaurant_number",
        ),
    )
    op.create_table(
        "e_invoice_transmissions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False, index=True
        ),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("asp_provider", sa.String(64), server_default="mock", nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("transmitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "data_retention_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("purged_counts", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("status", sa.String(16), server_default="completed", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    for table in ("refund_notes", "e_invoice_transmissions", "data_retention_runs"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};"
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in ("data_retention_runs", "e_invoice_transmissions", "refund_notes"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
        op.drop_table(table)
    op.drop_column("dishes", "vat_rate")
    op.drop_column("orders", "tax_pricing_mode")
    op.drop_column("orders", "invoice_kind")
    op.drop_column("order_items", "vat_amount_aed")
    op.drop_column("order_items", "vat_rate")
