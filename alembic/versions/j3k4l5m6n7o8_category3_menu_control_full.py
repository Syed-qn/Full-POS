"""category3 menu control full

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "j3k4l5m6n7o8"
down_revision = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("categories.id"), nullable=True),
    )
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])

    op.add_column("dishes", sa.Column("name_ar", sa.String(255), nullable=True))
    op.add_column("dishes", sa.Column("description_ar", sa.String(2000), nullable=True))
    op.add_column(
        "dishes",
        sa.Column("nutrition", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.add_column(
        "dishes",
        sa.Column("channels_allowed", postgresql.JSONB(), server_default="[]", nullable=False),
    )
    op.add_column("dishes", sa.Column("brand_menu_code", sa.String(64), nullable=True))
    op.create_index("ix_dishes_brand_menu_code", "dishes", ["brand_menu_code"])
    op.add_column("dishes", sa.Column("stock_remaining", sa.Integer(), nullable=True))
    op.add_column(
        "dishes",
        sa.Column("auto_hide_when_oos", sa.Boolean(), server_default="false", nullable=False),
    )

    op.add_column(
        "dish_price_rules",
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=True),
    )
    op.create_index("ix_dish_price_rules_branch_id", "dish_price_rules", ["branch_id"])

    op.create_table(
        "menu_sell_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("rule_kind", sa.String(16), nullable=False),
        sa.Column("trigger_dish_id", sa.BigInteger(), sa.ForeignKey("dishes.id"), nullable=True),
        sa.Column("trigger_category", sa.String(128), nullable=True),
        sa.Column("suggest_dish_id", sa.BigInteger(), sa.ForeignKey("dishes.id"), nullable=False),
        sa.Column("message", sa.String(256), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_menu_sell_rules_restaurant_id", "menu_sell_rules", ["restaurant_id"])
    op.execute(
        """
        CREATE TRIGGER trg_menu_sell_rules_updated_at
        BEFORE UPDATE ON menu_sell_rules
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_menu_sell_rules_updated_at ON menu_sell_rules")
    op.drop_table("menu_sell_rules")
    op.drop_index("ix_dish_price_rules_branch_id", table_name="dish_price_rules")
    op.drop_column("dish_price_rules", "branch_id")
    op.drop_column("dishes", "auto_hide_when_oos")
    op.drop_column("dishes", "stock_remaining")
    op.drop_index("ix_dishes_brand_menu_code", table_name="dishes")
    op.drop_column("dishes", "brand_menu_code")
    op.drop_column("dishes", "channels_allowed")
    op.drop_column("dishes", "nutrition")
    op.drop_column("dishes", "description_ar")
    op.drop_column("dishes", "name_ar")
    op.drop_index("ix_categories_parent_id", table_name="categories")
    op.drop_column("categories", "parent_id")
