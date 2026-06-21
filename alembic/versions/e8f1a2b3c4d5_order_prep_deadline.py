"""order prep deadline (kitchen plate-by countdown)

Adds orders.prep_deadline — the distance-driven "plate by" time the kitchen must hit
so there is still enough of the 40-min SLA left to drive the order to the customer.
Computed at confirm/modify from the delivery drive leg; null when the order has no
geocoded drop-off.

Revision ID: e8f1a2b3c4d5
Revises: b7c8d9e0f1a2
Create Date: 2026-06-22
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("prep_deadline", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "prep_deadline")
