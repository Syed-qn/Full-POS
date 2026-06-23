"""dish serving-size variants + order_item variant snapshot

Adds dishes.variants (JSONB list of {name, price_aed, dish_number}, default []) so a dish
can offer serving sizes (e.g. Chicken Biryani → 1 serve / 4 serve) each with its own price,
and order_items.variant_name (nullable) to snapshot the chosen size on the order line.
Existing dishes get [] and behave exactly as before (flat, base price_aed).

Revision ID: d7e8f9a0b1c2
Revises: f9a2b3c4d5e6
Create Date: 2026-06-23
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "f9a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dishes",
        sa.Column(
            "variants",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_name", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "variant_name")
    op.drop_column("dishes", "variants")
