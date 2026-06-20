"""rider push token (native app push notifications)

Adds riders.push_token — the Expo push token the native app registers so the
backend can wake the rider when a delivery is assigned.

Revision ID: b7c8d9e0f1a2
Revises: d5e6f7a8b9c0
Create Date: 2026-06-20
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("riders", sa.Column("push_token", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("riders", "push_token")
