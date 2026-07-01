"""add orders.coupon_discount_aed and orders.distance_source (W5)

W5 money & catalogue price integrity:
- coupon_discount_aed: persisted coupon discount so recompute_order_total re-applies
  it verbatim on modify/redeem/confirm (F26/F41).
- distance_source: "road" | "haversine_fallback" so fee basis is auditable and a
  degraded geo quote is visible (F112/F31).

Revision ID: m6f7a8b9c0d1
Revises: l5e6f7a8b9c0
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = "m6f7a8b9c0d1"
down_revision = "l5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "coupon_discount_aed",
            sa.Numeric(8, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column("distance_source", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "distance_source")
    op.drop_column("orders", "coupon_discount_aed")
