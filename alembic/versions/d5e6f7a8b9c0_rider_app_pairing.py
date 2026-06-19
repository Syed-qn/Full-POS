"""rider app pairing + device auth (native rider app)

Columns on riders to support the Android rider app:
  * device_token            — long-lived bearer the app stores after pairing.
  * pairing_code            — short one-time code sent to the rider via WhatsApp.
  * pairing_code_expires_at — pairing code TTL.

Revision ID: d5e6f7a8b9c0
Revises: c4a8b1f7d2e1
Create Date: 2026-06-19
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4a8b1f7d2e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("riders", sa.Column("device_token", sa.String(length=64), nullable=True))
    op.add_column("riders", sa.Column("pairing_code", sa.String(length=12), nullable=True))
    op.add_column(
        "riders",
        sa.Column("pairing_code_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_riders_device_token"), "riders", ["device_token"], unique=True
    )
    op.create_index(op.f("ix_riders_pairing_code"), "riders", ["pairing_code"])


def downgrade() -> None:
    op.drop_index(op.f("ix_riders_pairing_code"), table_name="riders")
    op.drop_index(op.f("ix_riders_device_token"), table_name="riders")
    op.drop_column("riders", "pairing_code_expires_at")
    op.drop_column("riders", "pairing_code")
    op.drop_column("riders", "device_token")
