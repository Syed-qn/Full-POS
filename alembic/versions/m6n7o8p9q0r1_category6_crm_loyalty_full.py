"""category6 crm loyalty full

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "m6n7o8p9q0r1"
down_revision = "l5m6n7o8p9q0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("notes", sa.String(1024), nullable=True))
    op.add_column("customers", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("customers", sa.Column("anniversary", sa.Date(), nullable=True))
    op.add_column(
        "customers",
        sa.Column("is_vip", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "customers",
        sa.Column("loyalty_points", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "customer_phone_history",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("changed_by", sa.String(64), server_default="manager", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_customer_phone_history_restaurant_id", "customer_phone_history", ["restaurant_id"]
    )
    op.create_index(
        "ix_customer_phone_history_customer_id", "customer_phone_history", ["customer_id"]
    )

    op.create_table(
        "customer_favorites",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("dish_id", sa.Integer(), sa.ForeignKey("dishes.id"), nullable=True),
        sa.Column("dish_name", sa.String(128), nullable=False),
        sa.Column("order_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "restaurant_id",
            "customer_id",
            "dish_id",
            name="uq_customer_favorites_rest_cust_dish",
        ),
    )
    op.create_index(
        "ix_customer_favorites_restaurant_id", "customer_favorites", ["restaurant_id"]
    )
    op.create_index("ix_customer_favorites_customer_id", "customer_favorites", ["customer_id"])

    # stamp_cards may exist from earlier partial work — create if missing
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "stamp_cards" not in insp.get_table_names():
        op.create_table(
            "stamp_cards",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False
            ),
            sa.Column(
                "customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False
            ),
            sa.Column("stamps", sa.Integer(), server_default="0", nullable=False),
            sa.Column("rewards_redeemed", sa.Integer(), server_default="0", nullable=False),
            sa.Column("stamps_required", sa.Integer(), server_default="10", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint(
                "restaurant_id", "customer_id", name="uq_stamp_cards_restaurant_customer"
            ),
        )
        op.create_index("ix_stamp_cards_restaurant_id", "stamp_cards", ["restaurant_id"])
        op.create_index("ix_stamp_cards_customer_id", "stamp_cards", ["customer_id"])
    else:
        cols = {c["name"] for c in insp.get_columns("stamp_cards")}
        if "stamps_required" not in cols:
            op.add_column(
                "stamp_cards",
                sa.Column("stamps_required", sa.Integer(), server_default="10", nullable=False),
            )

    op.create_table(
        "loyalty_point_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_loyalty_point_entries_idem"),
    )
    op.create_index(
        "ix_loyalty_point_entries_restaurant_id", "loyalty_point_entries", ["restaurant_id"]
    )
    op.create_index(
        "ix_loyalty_point_entries_customer_id", "loyalty_point_entries", ["customer_id"]
    )


def downgrade() -> None:
    op.drop_table("loyalty_point_entries")
    op.drop_table("customer_favorites")
    op.drop_table("customer_phone_history")
    op.drop_column("customers", "loyalty_points")
    op.drop_column("customers", "is_vip")
    op.drop_column("customers", "anniversary")
    op.drop_column("customers", "birthday")
    op.drop_column("customers", "notes")
