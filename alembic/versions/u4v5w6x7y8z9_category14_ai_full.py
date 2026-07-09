"""category14 ai features full

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "u4v5w6x7y8z9"
down_revision = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_insights",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(48), nullable=False, index=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
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
        "review_reply_suggestions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("nps_response_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("original_comment", sa.Text(), nullable=True),
        sa.Column("suggested_reply", sa.Text(), nullable=False),
        sa.Column("sentiment", sa.String(24), server_default="neutral", nullable=False),
        sa.Column("escalated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ticket_id", sa.BigInteger(), nullable=True),
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
        "reservation_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("guest_name", sa.String(128), nullable=True),
        sa.Column("party_size", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("requested_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("table_id", sa.BigInteger(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), server_default="dashboard", nullable=False),
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
        "call_answer_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("caller_phone", sa.String(32), nullable=True),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        sa.Column(
            "transcript",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(48), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
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
        "menu_translations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "restaurant_id",
            sa.BigInteger(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "dish_id", sa.BigInteger(), sa.ForeignKey("dishes.id"), nullable=False, index=True
        ),
        sa.Column("source_lang", sa.String(8), server_default="en", nullable=False),
        sa.Column("target_lang", sa.String(8), server_default="ar", nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "restaurant_id",
            "dish_id",
            "target_lang",
            name="uq_menu_translations_dish_lang",
        ),
    )
    for table in (
        "ai_insights",
        "review_reply_suggestions",
        "reservation_requests",
        "call_answer_sessions",
        "menu_translations",
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
        "menu_translations",
        "call_answer_sessions",
        "reservation_requests",
        "review_reply_suggestions",
        "ai_insights",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
        op.drop_table(table)
