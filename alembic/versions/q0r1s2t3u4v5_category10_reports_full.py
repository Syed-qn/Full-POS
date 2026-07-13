"""category10 reporting full

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "q0r1s2t3u4v5"
down_revision = "p9q0r1s2t3u4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "owner_report_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("to_phone", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="sent", nullable=False),
        sa.Column("body_preview", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
        DROP TRIGGER IF EXISTS trg_owner_report_deliveries_updated_at ON owner_report_deliveries;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_owner_report_deliveries_updated_at
        BEFORE UPDATE ON owner_report_deliveries
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_owner_report_deliveries_updated_at ON owner_report_deliveries;"
    )
    op.drop_table("owner_report_deliveries")
