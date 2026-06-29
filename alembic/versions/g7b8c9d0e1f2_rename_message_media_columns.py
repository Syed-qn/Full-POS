"""rename messages audio_* columns to media_* (all attachment types)

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-29
"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("messages", "audio_data", new_column_name="media_data")
    op.alter_column("messages", "audio_mime", new_column_name="media_mime")


def downgrade() -> None:
    op.alter_column("messages", "media_data", new_column_name="audio_data")
    op.alter_column("messages", "media_mime", new_column_name="audio_mime")