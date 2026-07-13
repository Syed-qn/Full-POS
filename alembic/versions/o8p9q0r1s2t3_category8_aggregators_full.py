"""category8 aggregators and channels full

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "o8p9q0r1s2t3"
down_revision = "n7o8p9q0r1s2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "restaurants",
        sa.Column("public_slug", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_restaurants_public_slug",
        "restaurants",
        ["public_slug"],
        unique=True,
    )
    op.add_column(
        "orders",
        sa.Column("source_channel", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_orders_restaurant_source_channel",
        "orders",
        ["restaurant_id", "source_channel"],
    )

    op.create_table(
        "channel_sync_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("success", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("items_touched", sa.Integer(), server_default="0", nullable=False),
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
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_channel_sync_logs_updated_at ON channel_sync_logs;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_sync_logs_updated_at
        BEFORE UPDATE ON channel_sync_logs
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.create_table(
        "channel_settlements",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False, index=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("order_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "gross_revenue_aed",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "commission_aed",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "net_aed", sa.Numeric(12, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "status", sa.String(24), server_default="recorded", nullable=False
        ),
        sa.Column("external_ref", sa.String(128), nullable=True),
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
        sa.UniqueConstraint(
            "restaurant_id",
            "provider",
            "period_start",
            "period_end",
            name="uq_channel_settlements_period",
        ),
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_channel_settlements_updated_at ON channel_settlements;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_settlements_updated_at
        BEFORE UPDATE ON channel_settlements
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_channel_settlements_updated_at ON channel_settlements;")
    op.drop_table("channel_settlements")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_sync_logs_updated_at ON channel_sync_logs;")
    op.drop_table("channel_sync_logs")
    op.drop_index("ix_orders_restaurant_source_channel", table_name="orders")
    op.drop_column("orders", "source_channel")
    op.drop_index("ix_restaurants_public_slug", table_name="restaurants")
    op.drop_column("restaurants", "public_slug")
