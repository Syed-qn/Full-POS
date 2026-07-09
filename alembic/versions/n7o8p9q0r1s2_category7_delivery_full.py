"""category7 delivery full

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "n7o8p9q0r1s2"
down_revision = "m6n7o8p9q0r1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_addresses",
        sa.Column("floor", sa.String(64), nullable=True),
    )
    # Optional local-path storage for delivery proof photos (alongside URL).
    op.add_column(
        "orders",
        sa.Column("delivery_photo_path", sa.String(512), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "otp_required_at_deliver",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "otp_required_at_deliver")
    op.drop_column("orders", "delivery_photo_path")
    op.drop_column("customer_addresses", "floor")
