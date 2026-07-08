"""stock adjustment approval requests

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-07-09
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "z7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "y6z7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_adjustment_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_qty", sa.Numeric(10, 3), nullable=False),
        sa.Column("previous_qty_snapshot", sa.Numeric(10, 3), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_stock_adjustment_requests_ingredient_id"),
        "stock_adjustment_requests",
        ["ingredient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stock_adjustment_requests_restaurant_id"),
        "stock_adjustment_requests",
        ["restaurant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stock_adjustment_requests_status"),
        "stock_adjustment_requests",
        ["status"],
        unique=False,
    )
    op.execute(
        "CREATE TRIGGER trg_stock_adjustment_requests_updated_at "
        "BEFORE UPDATE ON stock_adjustment_requests "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_stock_adjustment_requests_updated_at "
        "ON stock_adjustment_requests;"
    )
    op.drop_index(
        op.f("ix_stock_adjustment_requests_status"),
        table_name="stock_adjustment_requests",
    )
    op.drop_index(
        op.f("ix_stock_adjustment_requests_restaurant_id"),
        table_name="stock_adjustment_requests",
    )
    op.drop_index(
        op.f("ix_stock_adjustment_requests_ingredient_id"),
        table_name="stock_adjustment_requests",
    )
    op.drop_table("stock_adjustment_requests")
