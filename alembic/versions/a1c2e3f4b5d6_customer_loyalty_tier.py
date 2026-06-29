"""customer loyalty tier columns

Adds the denormalized loyalty tier cache to customers: tier, since, manager lock,
and reward anchor (total_orders at tier entry, for "every N orders" rewards).

Revision ID: a1c2e3f4b5d6
Revises: 1b4d8479d894
Create Date: 2026-06-29
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c2e3f4b5d6"
down_revision: Union[str, Sequence[str], None] = "1b4d8479d894"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("loyalty_tier", sa.String(length=12), nullable=True))
    op.add_column("customers", sa.Column("loyalty_tier_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "customers",
        sa.Column("loyalty_tier_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "customers",
        sa.Column("loyalty_reward_anchor", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("customers", "loyalty_reward_anchor")
    op.drop_column("customers", "loyalty_tier_locked")
    op.drop_column("customers", "loyalty_tier_since")
    op.drop_column("customers", "loyalty_tier")
