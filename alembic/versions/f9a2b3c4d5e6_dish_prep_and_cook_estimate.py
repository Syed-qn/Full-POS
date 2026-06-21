"""dish prep_minutes + order cook_estimate_minutes (kitchen "start by")

Adds dishes.prep_minutes (per-portion cook time, nullable) and orders.cook_estimate_minutes
(slowest-dish gated cook estimate, set at confirm/modify). Together with prep_deadline they
give the kitchen a "start cooking by" signal.

Revision ID: f9a2b3c4d5e6
Revises: e8f1a2b3c4d5
Create Date: 2026-06-22
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e8f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dishes", sa.Column("prep_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "orders", sa.Column("cook_estimate_minutes", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("orders", "cook_estimate_minutes")
    op.drop_column("dishes", "prep_minutes")
