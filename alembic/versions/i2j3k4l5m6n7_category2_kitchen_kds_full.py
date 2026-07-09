"""category2 kitchen kds full

Revision ID: i2j3k4l5m6n7
Revises: h1j2k3l4m5n6
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "i2j3k4l5m6n7"
down_revision = "h1j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kitchen_stations",
        sa.Column("station_type", sa.String(24), server_default="general", nullable=False),
    )
    op.add_column(
        "kitchen_stations",
        sa.Column("kitchen_code", sa.String(32), server_default="main", nullable=False),
    )
    op.add_column(
        "kitchen_stations",
        sa.Column("fallback_station_id", sa.BigInteger(), sa.ForeignKey("kitchen_stations.id"), nullable=True),
    )
    op.add_column(
        "kitchen_stations",
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    )
    # Drop loose uniqueness if any and add (restaurant, kitchen_code, name)
    op.create_index(
        "ix_kitchen_stations_restaurant_kitchen_code",
        "kitchen_stations",
        ["restaurant_id", "kitchen_code"],
    )

    op.add_column(
        "print_jobs",
        sa.Column("via_fallback", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "print_jobs",
        sa.Column("original_station_id", sa.BigInteger(), sa.ForeignKey("kitchen_stations.id"), nullable=True),
    )

    op.add_column(
        "order_items",
        sa.Column("bumped_by_staff_id", sa.BigInteger(), sa.ForeignKey("staff_members.id"), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("kitchen_received_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("kitchen_code_snapshot", sa.String(32), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("missing_item_confirmed", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "order_items",
        sa.Column("missing_item_note", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "missing_item_note")
    op.drop_column("order_items", "missing_item_confirmed")
    op.drop_column("order_items", "kitchen_code_snapshot")
    op.drop_column("order_items", "kitchen_received_at")
    op.drop_column("order_items", "bumped_by_staff_id")

    op.drop_column("print_jobs", "original_station_id")
    op.drop_column("print_jobs", "via_fallback")

    op.drop_index("ix_kitchen_stations_restaurant_kitchen_code", table_name="kitchen_stations")
    op.drop_column("kitchen_stations", "is_active")
    op.drop_column("kitchen_stations", "fallback_station_id")
    op.drop_column("kitchen_stations", "kitchen_code")
    op.drop_column("kitchen_stations", "station_type")
