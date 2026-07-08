"""dish_price_rules: time/channel/branch dish pricing rules

Revision ID: v3w4x5y6z7a8
Revises: 122f2270dfbc
Create Date: 2026-07-08
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v3w4x5y6z7a8"
down_revision: Union[str, Sequence[str], None] = "122f2270dfbc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dish_price_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(length=16), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("days_of_week", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("price_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dish_price_rules_restaurant_id", "dish_price_rules", ["restaurant_id"],
    )
    op.create_index(
        "ix_dish_price_rules_dish_id", "dish_price_rules", ["dish_id"],
    )
    op.execute(
        "CREATE TRIGGER trg_dish_price_rules_updated_at "
        "BEFORE UPDATE ON dish_price_rules "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_dish_price_rules_updated_at ON dish_price_rules;")
    op.drop_index("ix_dish_price_rules_dish_id", table_name="dish_price_rules")
    op.drop_index("ix_dish_price_rules_restaurant_id", table_name="dish_price_rules")
    op.drop_table("dish_price_rules")
