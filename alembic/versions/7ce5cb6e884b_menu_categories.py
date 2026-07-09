"""menu categories

Revision ID: 7ce5cb6e884b
Revises: z7a8b9c0d1e2
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "7ce5cb6e884b"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_categories_restaurant_name"),
    )
    op.create_index("ix_categories_restaurant_id", "categories", ["restaurant_id"])
    op.execute(
        """
        CREATE TRIGGER trg_categories_updated_at
        BEFORE UPDATE ON categories
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    op.add_column("dishes", sa.Column("category_id", sa.BigInteger(), sa.ForeignKey("categories.id"), nullable=True))
    op.create_index("ix_dishes_category_id", "dishes", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_dishes_category_id", table_name="dishes")
    op.drop_column("dishes", "category_id")
    op.execute("DROP TRIGGER IF EXISTS trg_categories_updated_at ON categories;")
    op.drop_index("ix_categories_restaurant_id", table_name="categories")
    op.drop_table("categories")
