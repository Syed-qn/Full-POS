"""add dishes.pos_product_id

Stable external POS product id (e.g. Cratis posProductId) for dishes mirrored from a POS.
Null for manually-managed dishes. The POS sync owns only dishes with this set.

Revision ID: m6f7a8b9c0d1
Revises: l5e6f7a8b9c0
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "m6f7a8b9c0d1"
down_revision = "l5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dishes", sa.Column("pos_product_id", sa.String(length=64), nullable=True))
    op.create_index("ix_dishes_pos_product_id", "dishes", ["pos_product_id"])


def downgrade() -> None:
    op.drop_index("ix_dishes_pos_product_id", table_name="dishes")
    op.drop_column("dishes", "pos_product_id")
