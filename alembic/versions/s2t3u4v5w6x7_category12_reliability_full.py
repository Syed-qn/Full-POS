"""category12 offline backup reliability full

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "s2t3u4v5w6x7"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id"), nullable=False, index=True),
        sa.Column("kind", sa.String(24), server_default="manual", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False, index=True),
        sa.Column("storage_path", sa.String(512), nullable=True),
        sa.Column("size_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "device_registrations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id"), nullable=False, index=True),
        sa.Column("device_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("device_type", sa.String(24), server_default="pos", nullable=False),
        sa.Column("role", sa.String(16), server_default="primary", nullable=False),
        sa.Column("status", sa.String(16), server_default="online", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_failover_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("restaurant_id", "device_id", name="uq_device_restaurant"),
    )
    op.create_table(
        "app_error_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id"), nullable=True, index=True),
        sa.Column("level", sa.String(16), server_default="error", nullable=False),
        sa.Column("source", sa.String(64), server_default="api", nullable=False),
        sa.Column("message", sa.String(512), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("acknowledged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "offline_payment_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id"), nullable=False, index=True),
        sa.Column("client_payment_id", sa.String(64), nullable=False, index=True),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("amount_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("tender_type", sa.String(24), server_default="cash", nullable=False),
        sa.Column("status", sa.String(16), server_default="applied", nullable=False),
        sa.Column("device_id", sa.String(64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "dr_drill_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id"), nullable=False, index=True),
        sa.Column("backup_job_id", sa.BigInteger(), sa.ForeignKey("backup_jobs.id"), nullable=True),
        sa.Column("kind", sa.String(16), server_default="drill", nullable=False),
        sa.Column("status", sa.String(16), server_default="ok", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    for table in (
        "backup_jobs",
        "device_registrations",
        "app_error_logs",
        "offline_payment_ledger",
        "dr_drill_logs",
    ):
        op.execute(
            f"""
            DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in (
        "dr_drill_logs",
        "offline_payment_ledger",
        "app_error_logs",
        "device_registrations",
        "backup_jobs",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
        op.drop_table(table)
