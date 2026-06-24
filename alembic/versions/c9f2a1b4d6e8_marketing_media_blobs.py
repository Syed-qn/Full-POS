"""marketing_media: DB-backed header-image blobs

Stores marketing template header images in Postgres instead of local disk so
they survive redeploys on ephemeral-disk hosts (Render free tier). Keyed by the
relative media path ("marketing/<rid>/<uuid>.<ext>") so the existing
/media/<path> URL scheme is unchanged.

Revision ID: c9f2a1b4d6e8
Revises: d7e8f9a0b1c2
Create Date: 2026-06-24
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9f2a1b4d6e8"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "marketing_media",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.String(length=256), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", name="uq_marketing_media_path"),
    )
    op.create_index(
        "ix_marketing_media_restaurant_id", "marketing_media", ["restaurant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_marketing_media_restaurant_id", table_name="marketing_media")
    op.drop_table("marketing_media")
