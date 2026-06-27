"""add dishes.catalog_retailer_id for WhatsApp catalog ordering

Revision ID: d1a2c3e4f5b6
Revises: b4e7c2a9f1d3
Create Date: 2026-06-27

Links a dish to its Meta Commerce catalog product (the "Content ID" / retailer id)
so a cart sent from the WhatsApp catalog can be matched back to the dish. Used only
by the separate catalog flow.
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "d1a2c3e4f5b6"
down_revision: Union[str, Sequence[str], None] = "b4e7c2a9f1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dishes",
        sa.Column("catalog_retailer_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_dishes_catalog_retailer_id", "dishes", ["catalog_retailer_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_dishes_catalog_retailer_id", table_name="dishes")
    op.drop_column("dishes", "catalog_retailer_id")
