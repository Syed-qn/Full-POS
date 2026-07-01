"""add orders.coupon_discount_aed and orders.distance_source (W5)

W5 money & catalogue price integrity:
- coupon_discount_aed: persisted coupon discount so recompute_order_total re-applies
  it verbatim on modify/redeem/confirm (F26/F41).
- distance_source: "road" | "haversine_fallback" so fee basis is auditable and a
  degraded geo quote is visible (F112/F31).

Revision ID: q7r8s9t0u1v2
Revises: m6f7a8b9c0d1
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = "q7r8s9t0u1v2"
down_revision = "m6f7a8b9c0d1"
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
