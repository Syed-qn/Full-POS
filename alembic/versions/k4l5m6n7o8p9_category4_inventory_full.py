"""category4 inventory full

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "k4l5m6n7o8p9"
down_revision = "j3k4l5m6n7o8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_locations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("kitchen_role", sa.String(16), server_default="branch", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("restaurant_id", "code", name="uq_stock_locations_restaurant_code"),
    )
    op.create_index("ix_stock_locations_restaurant_id", "stock_locations", ["restaurant_id"])

    op.add_column(
        "ingredients",
        sa.Column("location_id", sa.BigInteger(), sa.ForeignKey("stock_locations.id"), nullable=True),
    )
    op.add_column(
        "ingredients",
        sa.Column("preferred_vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=True),
    )

    op.add_column(
        "dish_ingredients",
        sa.Column("yield_pct", sa.Numeric(5, 2), server_default="100.00", nullable=False),
    )

    op.add_column(
        "waste_log",
        sa.Column("reason_type", sa.String(16), server_default="wastage", nullable=False),
    )
    op.add_column(
        "waste_log",
        sa.Column("batch_id", sa.BigInteger(), sa.ForeignKey("ingredient_batches.id"), nullable=True),
    )

    op.add_column(
        "vendors",
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column("vendors", sa.Column("notes", sa.String(256), nullable=True))

    op.add_column("purchase_orders", sa.Column("notes", sa.String(256), nullable=True))
    op.add_column(
        "purchase_order_lines",
        sa.Column("qty_received", sa.Numeric(10, 3), server_default="0", nullable=False),
    )

    op.add_column(
        "ingredient_batches",
        sa.Column("qty_remaining", sa.Numeric(10, 3), server_default="0", nullable=False),
    )
    op.add_column(
        "ingredient_batches",
        sa.Column("location_id", sa.BigInteger(), sa.ForeignKey("stock_locations.id"), nullable=True),
    )
    # Backfill qty_remaining = qty for existing batches
    op.execute("UPDATE ingredient_batches SET qty_remaining = qty WHERE qty_remaining = 0 AND qty > 0")

    op.add_column(
        "ingredient_substitutes",
        sa.Column("conversion_factor", sa.Numeric(10, 4), server_default="1", nullable=False),
    )
    op.add_column(
        "ingredient_substitutes",
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "goods_received_notes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("po_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("grn_number", sa.String(32), nullable=False),
        sa.Column("received_by", sa.String(64), nullable=False),
        sa.Column("notes", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_goods_received_notes_restaurant_id", "goods_received_notes", ["restaurant_id"])
    op.create_index("ix_goods_received_notes_po_id", "goods_received_notes", ["po_id"])
    op.create_index("ix_goods_received_notes_grn_number", "goods_received_notes", ["grn_number"])

    op.create_table(
        "goods_received_lines",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("grn_id", sa.BigInteger(), sa.ForeignKey("goods_received_notes.id"), nullable=False),
        sa.Column("po_line_id", sa.Integer(), sa.ForeignKey("purchase_order_lines.id"), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), sa.ForeignKey("ingredients.id"), nullable=False),
        sa.Column("qty_received", sa.Numeric(10, 3), nullable=False),
        sa.Column("unit_cost_aed", sa.Numeric(10, 4), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_goods_received_lines_grn_id", "goods_received_lines", ["grn_id"])

    op.create_table(
        "stock_count_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), sa.ForeignKey("ingredients.id"), nullable=False),
        sa.Column("previous_stock", sa.Numeric(10, 3), nullable=False),
        sa.Column("counted_stock", sa.Numeric(10, 3), nullable=False),
        sa.Column("variance", sa.Numeric(10, 3), nullable=False),
        sa.Column("counted_by", sa.String(64), server_default="manager", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stock_count_logs_restaurant_id", "stock_count_logs", ["restaurant_id"])

    op.create_table(
        "stock_closing_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), sa.ForeignKey("ingredients.id"), nullable=False),
        sa.Column("closing_date", sa.Date(), nullable=False),
        sa.Column("closing_stock", sa.Numeric(10, 3), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("valuation_aed", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "restaurant_id", "ingredient_id", "closing_date", name="uq_stock_closing_rest_ing_date"
        ),
    )
    op.create_index(
        "ix_stock_closing_snapshots_restaurant_id", "stock_closing_snapshots", ["restaurant_id"]
    )
    op.create_index(
        "ix_stock_closing_snapshots_closing_date", "stock_closing_snapshots", ["closing_date"]
    )

    op.create_table(
        "stock_anomaly_alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), sa.ForeignKey("ingredients.id"), nullable=False),
        sa.Column("alert_type", sa.String(24), nullable=False),
        sa.Column("expected_qty", sa.Numeric(10, 3), nullable=False),
        sa.Column("actual_qty", sa.Numeric(10, 3), nullable=False),
        sa.Column("variance_pct", sa.Numeric(8, 2), nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("message", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_stock_anomaly_alerts_restaurant_id", "stock_anomaly_alerts", ["restaurant_id"]
    )


def downgrade() -> None:
    op.drop_table("stock_anomaly_alerts")
    op.drop_table("stock_closing_snapshots")
    op.drop_table("stock_count_logs")
    op.drop_table("goods_received_lines")
    op.drop_table("goods_received_notes")
    op.drop_column("ingredient_substitutes", "priority")
    op.drop_column("ingredient_substitutes", "conversion_factor")
    op.drop_column("ingredient_batches", "location_id")
    op.drop_column("ingredient_batches", "qty_remaining")
    op.drop_column("purchase_order_lines", "qty_received")
    op.drop_column("purchase_orders", "notes")
    op.drop_column("vendors", "notes")
    op.drop_column("vendors", "is_active")
    op.drop_column("waste_log", "batch_id")
    op.drop_column("waste_log", "reason_type")
    op.drop_column("dish_ingredients", "yield_pct")
    op.drop_column("ingredients", "preferred_vendor_id")
    op.drop_column("ingredients", "location_id")
    op.drop_table("stock_locations")
