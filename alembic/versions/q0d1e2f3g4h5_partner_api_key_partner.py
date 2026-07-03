"""partner_api_keys: add partner slug column (multi-partner attribution)

Tags each API key with the partner it was minted for (cratis, pos2, …) so keys
can be filtered/revoked per partner. Nullable — existing keys predate the split.

Revision ID: q0d1e2f3g4h5
Revises: p9c0d1e2f3g4
Create Date: 2026-07-03
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "q0d1e2f3g4h5"
down_revision: Union[str, Sequence[str], None] = "p9c0d1e2f3g4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "partner_api_keys",
        sa.Column("partner", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_partner_api_keys_partner", "partner_api_keys", ["partner"]
    )


def downgrade() -> None:
    op.drop_index("ix_partner_api_keys_partner", table_name="partner_api_keys")
    op.drop_column("partner_api_keys", "partner")
