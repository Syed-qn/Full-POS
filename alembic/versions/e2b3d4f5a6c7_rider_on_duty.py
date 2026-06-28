"""add riders.on_duty for the in-app On duty / Off duty switch

Revision ID: e2b3d4f5a6c7
Revises: d1a2c3e4f5b6
Create Date: 2026-06-28

Rider-controlled duty flag, independent of the operational `status`. Dispatch only
assigns riders with on_duty = true. Defaults true so every existing rider stays
dispatchable after the migration.
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "e2b3d4f5a6c7"
down_revision: Union[str, Sequence[str], None] = "d1a2c3e4f5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "riders",
        sa.Column(
            "on_duty",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("riders", "on_duty")
