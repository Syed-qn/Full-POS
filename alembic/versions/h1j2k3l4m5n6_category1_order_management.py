"""category1 order management fields

Revision ID: h1j2k3l4m5n6
Revises: 7ce5cb6e884b
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "h1j2k3l4m5n6"
down_revision = "7ce5cb6e884b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("order_type", sa.String(24), server_default="delivery", nullable=False),
    )
    op.add_column("orders", sa.Column("held_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("held_reason", sa.String(256), nullable=True))
    op.add_column("orders", sa.Column("customer_allergy_notes", sa.String(512), nullable=True))
    op.add_column(
        "orders",
        sa.Column("is_preorder", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column("scheduled_released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_restaurant_order_type", "orders", ["restaurant_id", "order_type"])

    op.add_column("customers", sa.Column("allergy_notes", sa.String(512), nullable=True))

    op.add_column(
        "order_items",
        sa.Column("course_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "order_items",
        sa.Column("course_held", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("order_items", sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("tables", sa.Column("qr_token", sa.String(64), nullable=True))
    op.create_index("ix_tables_qr_token", "tables", ["qr_token"])
    op.create_unique_constraint("uq_tables_qr_token", "tables", ["qr_token"])


def downgrade() -> None:
    op.drop_constraint("uq_tables_qr_token", "tables", type_="unique")
    op.drop_index("ix_tables_qr_token", table_name="tables")
    op.drop_column("tables", "qr_token")

    op.drop_column("order_items", "fired_at")
    op.drop_column("order_items", "course_held")
    op.drop_column("order_items", "course_number")

    op.drop_column("customers", "allergy_notes")

    op.drop_index("ix_orders_restaurant_order_type", table_name="orders")
    op.drop_column("orders", "scheduled_released_at")
    op.drop_column("orders", "is_preorder")
    op.drop_column("orders", "customer_allergy_notes")
    op.drop_column("orders", "held_reason")
    op.drop_column("orders", "held_at")
    op.drop_column("orders", "order_type")
