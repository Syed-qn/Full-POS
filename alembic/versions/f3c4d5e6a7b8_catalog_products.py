"""add catalog_products (Meta catalogue mirror for the Sync feature)

Revision ID: f3c4d5e6a7b8
Revises: e2b3d4f5a6c7
Create Date: 2026-06-29

Stores products synced from the restaurant's Meta Commerce catalogue (OPS
"Sync from Meta"). One row per (restaurant_id, retailer_id).
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f3c4d5e6a7b8"
down_revision: Union[str, Sequence[str], None] = "e2b3d4f5a6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_products",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
        ),
        sa.Column("retailer_id", sa.String(length=128), nullable=False),
        sa.Column("meta_product_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("price_aed", sa.Numeric(8, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("availability", sa.String(length=32), nullable=True),
        sa.Column("image_url", sa.String(length=1024), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("restaurant_id", "retailer_id", name="uq_catalog_products_restaurant_retailer"),
    )
    op.create_index(
        "ix_catalog_products_restaurant_id", "catalog_products", ["restaurant_id"]
    )
    op.create_index(
        "ix_catalog_products_retailer_id", "catalog_products", ["retailer_id"]
    )
    # Keep updated_at fresh on UPDATE (project convention for TimestampMixin tables).
    op.execute(
        """
        CREATE TRIGGER trg_catalog_products_updated_at
        BEFORE UPDATE ON catalog_products
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_catalog_products_updated_at ON catalog_products;")
    op.drop_index("ix_catalog_products_retailer_id", table_name="catalog_products")
    op.drop_index("ix_catalog_products_restaurant_id", table_name="catalog_products")
    op.drop_table("catalog_products")
