"""category9 staff and permissions full

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "p9q0r1s2t3u4"
down_revision = "o8p9q0r1s2t3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "staff_members",
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "staff_members",
        sa.Column("training_mode", sa.Boolean(), server_default="false", nullable=False),
    )

    op.add_column(
        "shifts",
        sa.Column("status", sa.String(16), server_default="scheduled", nullable=False),
    )
    op.add_column(
        "shifts",
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "shifts",
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "cash_drawer_sessions",
        sa.Column("staff_id", sa.BigInteger(), sa.ForeignKey("staff_members.id"), nullable=True),
    )
    op.create_index(
        "ix_cash_drawer_sessions_staff_id",
        "cash_drawer_sessions",
        ["staff_id"],
    )

    op.add_column(
        "orders",
        sa.Column("is_training", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column("tip_staff_id", sa.BigInteger(), sa.ForeignKey("staff_members.id"), nullable=True),
    )

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column(
            "requested_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("staff_members.id"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("staff_members.id"),
            nullable=True,
        ),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("amount_aed", sa.Numeric(8, 2), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("reason", sa.String(256), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_approval_requests_status", "approval_requests", ["restaurant_id", "status"])

    op.create_table(
        "staff_mistakes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("staff_members.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("mistake_type", sa.String(32), nullable=False),
        sa.Column(
            "amount_aed",
            sa.Numeric(8, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("notes", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "suspicious_activity_alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("alert_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), server_default="medium", nullable=False),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("staff_members.id"),
            nullable=True,
        ),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("acknowledged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_approval_requests_updated_at ON approval_requests;
        CREATE TRIGGER trg_approval_requests_updated_at
        BEFORE UPDATE ON approval_requests
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_staff_mistakes_updated_at ON staff_mistakes;
        CREATE TRIGGER trg_staff_mistakes_updated_at
        BEFORE UPDATE ON staff_mistakes
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_suspicious_activity_alerts_updated_at ON suspicious_activity_alerts;
        CREATE TRIGGER trg_suspicious_activity_alerts_updated_at
        BEFORE UPDATE ON suspicious_activity_alerts
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_suspicious_activity_alerts_updated_at ON suspicious_activity_alerts;")
    op.execute("DROP TRIGGER IF EXISTS trg_staff_mistakes_updated_at ON staff_mistakes;")
    op.execute("DROP TRIGGER IF EXISTS trg_approval_requests_updated_at ON approval_requests;")
    op.drop_table("suspicious_activity_alerts")
    op.drop_table("staff_mistakes")
    op.drop_table("approval_requests")
    op.drop_column("orders", "tip_staff_id")
    op.drop_column("orders", "is_training")
    op.drop_index("ix_cash_drawer_sessions_staff_id", table_name="cash_drawer_sessions")
    op.drop_column("cash_drawer_sessions", "staff_id")
    op.drop_column("shifts", "actual_end")
    op.drop_column("shifts", "actual_start")
    op.drop_column("shifts", "status")
    op.drop_column("staff_members", "training_mode")
    op.drop_column("staff_members", "is_active")
