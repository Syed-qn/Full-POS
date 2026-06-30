"""add catalog_products sendable + review_status

Tracks whether a Meta catalogue product has finished processing (image fetched onto
Meta's CDN + approved) and is therefore sendable in a WhatsApp product_list. A product
that is active but not yet sendable is "in review": kept off WhatsApp so the interactive
message can't fail with #131009, and shown with an "In review" pill in the dashboard
until Meta finishes.

  is_sendable    BOOLEAN NOT NULL DEFAULT true   (back-compat: existing rows stay live)
  review_status  VARCHAR(32) NULL                (Meta state, e.g. pending/approved)

Revision ID: k4d5e6f7a8b9
Revises: j3c4d5e6f7a8
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "k4d5e6f7a8b9"
down_revision = "j3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_products",
        sa.Column(
            "is_sendable", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column(
        "catalog_products",
        sa.Column("review_status", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("catalog_products", "review_status")
    op.drop_column("catalog_products", "is_sendable")
