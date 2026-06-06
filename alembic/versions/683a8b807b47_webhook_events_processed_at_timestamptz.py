"""webhook_events_processed_at_timestamptz

Revision ID: 683a8b807b47
Revises: eb6f4dfb6f23
Create Date: 2026-06-06 19:34:51.231790

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '683a8b807b47'
down_revision: Union[str, Sequence[str], None] = 'eb6f4dfb6f23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "webhook_events", "processed_at",
        existing_type=sa.String(length=64),
        type_=sa.DateTime(timezone=True),
        postgresql_using="processed_at::timestamptz",
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "webhook_events", "processed_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.String(length=64),
        postgresql_using="processed_at::text",
        existing_nullable=True,
    )
