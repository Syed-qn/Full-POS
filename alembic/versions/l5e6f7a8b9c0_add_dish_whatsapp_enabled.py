"""add dishes.whatsapp_enabled

Per-dish WhatsApp switch. True (default) → published to the Meta catalogue and shown on
WhatsApp once processed. False → unpublished from Meta and never linked/shown, regardless
of availability or review state.

Revision ID: l5e6f7a8b9c0
Revises: k4d5e6f7a8b9
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "l5e6f7a8b9c0"
down_revision = "k4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dishes",
        sa.Column(
            "whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )


def downgrade() -> None:
    op.drop_column("dishes", "whatsapp_enabled")
