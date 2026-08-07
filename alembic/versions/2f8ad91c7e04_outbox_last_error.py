"""outbox_messages.last_error — a failed send must say why

A row reading status='failed' with no reason is undiagnosable: the provider told
us exactly what was wrong and we discarded it. partner_webhook_deliveries already
carries last_error; the outbox now matches.

Revision ID: 2f8ad91c7e04
Revises: 9f4a1d8e3b62
Create Date: 2026-08-07
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "2f8ad91c7e04"
down_revision: Union[str, Sequence[str], None] = "9f4a1d8e3b62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outbox_messages", sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("outbox_messages", "last_error")
