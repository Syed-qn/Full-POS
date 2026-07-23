"""order sla acknowledgement

Records that a manager has SEEN a late order on the Live Ops board, so the
alert can be cleared server-side instead of per-device. Does NOT change the
order FSM or the SLA clock — the order is still late, just acknowledged.

Revision ID: a1b2c3d4e5f6
Revises: w4x5y6z7a8b9
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "w4x5y6z7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("sla_acked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("sla_acked_by_staff_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_sla_acked_by_staff_id",
        "orders",
        "staff_members",
        ["sla_acked_by_staff_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_orders_sla_acked_by_staff_id", "orders", type_="foreignkey")
    op.drop_column("orders", "sla_acked_by_staff_id")
    op.drop_column("orders", "sla_acked_at")
