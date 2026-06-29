"""messages: persist inbound voice-note audio for dashboard playback

Revision ID: f6a7b8c9d0e1
Revises: b2d4f6a8c0e2
Create Date: 2026-06-29
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "b2d4f6a8c0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("audio_data", sa.LargeBinary(), nullable=True))
    op.add_column("messages", sa.Column("audio_mime", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "audio_mime")
    op.drop_column("messages", "audio_data")