"""order_tracking_sessions

Revision ID: c4a8b1f7d2e1
Revises: fef0973b618c
Create Date: 2026-06-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4a8b1f7d2e1"
down_revision: Union[str, Sequence[str], None] = "fef0973b618c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rider_locations", sa.Column("accuracy", sa.Float(), nullable=True))
    op.add_column("rider_locations", sa.Column("speed", sa.Float(), nullable=True))
    op.add_column("rider_locations", sa.Column("heading", sa.Float(), nullable=True))

    op.create_table(
        "order_tracking_sessions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("rider_id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_token", sa.String(length=64), nullable=False),
        sa.Column("rider_token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latest_latitude", sa.Float(), nullable=True),
        sa.Column("latest_longitude", sa.Float(), nullable=True),
        sa.Column("latest_accuracy", sa.Float(), nullable=True),
        sa.Column("latest_speed", sa.Float(), nullable=True),
        sa.Column("latest_heading", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_location_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["rider_id"], ["riders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_tracking_sessions_order_id"), "order_tracking_sessions", ["order_id"], unique=True)
    op.create_index(op.f("ix_order_tracking_sessions_rider_id"), "order_tracking_sessions", ["rider_id"], unique=False)
    op.create_index(op.f("ix_order_tracking_sessions_restaurant_id"), "order_tracking_sessions", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_order_tracking_sessions_tracking_token"), "order_tracking_sessions", ["tracking_token"], unique=True)
    op.create_index(op.f("ix_order_tracking_sessions_rider_token"), "order_tracking_sessions", ["rider_token"], unique=True)
    op.create_index(op.f("ix_order_tracking_sessions_status"), "order_tracking_sessions", ["status"], unique=False)
    op.create_index(op.f("ix_order_tracking_sessions_expires_at"), "order_tracking_sessions", ["expires_at"], unique=False)
    op.execute(
        "CREATE TRIGGER trg_order_tracking_sessions_updated_at BEFORE UPDATE ON order_tracking_sessions "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_order_tracking_sessions_updated_at ON order_tracking_sessions;")
    op.drop_index(op.f("ix_order_tracking_sessions_expires_at"), table_name="order_tracking_sessions")
    op.drop_index(op.f("ix_order_tracking_sessions_status"), table_name="order_tracking_sessions")
    op.drop_index(op.f("ix_order_tracking_sessions_rider_token"), table_name="order_tracking_sessions")
    op.drop_index(op.f("ix_order_tracking_sessions_tracking_token"), table_name="order_tracking_sessions")
    op.drop_index(op.f("ix_order_tracking_sessions_restaurant_id"), table_name="order_tracking_sessions")
    op.drop_index(op.f("ix_order_tracking_sessions_rider_id"), table_name="order_tracking_sessions")
    op.drop_index(op.f("ix_order_tracking_sessions_order_id"), table_name="order_tracking_sessions")
    op.drop_table("order_tracking_sessions")
    op.drop_column("rider_locations", "heading")
    op.drop_column("rider_locations", "speed")
    op.drop_column("rider_locations", "accuracy")
