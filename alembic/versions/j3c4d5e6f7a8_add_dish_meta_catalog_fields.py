"""add dish Meta catalogue product fields

Adds the per-dish Meta Commerce "Add product" fields so a dish pushed to the
WhatsApp catalogue carries its own photo + optional commerce metadata:
  image_url, sale_price_aed, fb_product_category, condition, meta_status, brand.

Revision ID: j3c4d5e6f7a8
Revises: g7b8c9d0e1f2
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "j3c4d5e6f7a8"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dishes", sa.Column("image_url", sa.String(length=512), nullable=True))
    op.add_column("dishes", sa.Column("sale_price_aed", sa.Numeric(8, 2), nullable=True))
    op.add_column("dishes", sa.Column("fb_product_category", sa.String(length=128), nullable=True))
    op.add_column(
        "dishes",
        sa.Column("condition", sa.String(length=16), nullable=False, server_default="new"),
    )
    op.add_column(
        "dishes",
        sa.Column("meta_status", sa.String(length=16), nullable=False, server_default="active"),
    )
    op.add_column("dishes", sa.Column("brand", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("dishes", "brand")
    op.drop_column("dishes", "meta_status")
    op.drop_column("dishes", "condition")
    op.drop_column("dishes", "fb_product_category")
    op.drop_column("dishes", "sale_price_aed")
    op.drop_column("dishes", "image_url")
