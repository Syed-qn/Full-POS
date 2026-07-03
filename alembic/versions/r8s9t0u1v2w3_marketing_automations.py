"""marketing_automations

Revision ID: r8s9t0u1v2w3
Revises: p9c0d1e2f3g4
Create Date: 2026-07-03 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, Sequence[str], None] = "p9c0d1e2f3g4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "marketing_automations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("preset_key", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column("segment_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["wa_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "restaurant_id", "preset_key", name="uq_marketing_automation_preset"
        ),
    )
    op.create_index(
        op.f("ix_marketing_automations_restaurant_id"),
        "marketing_automations",
        ["restaurant_id"],
        unique=False,
    )

    op.create_table(
        "recurring_message_state",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("next_send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suppressed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phase", sa.String(length=8), nullable=False, server_default="day3"),
        sa.Column("weekday", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "usual_send_local_time",
            sa.String(length=5),
            nullable=False,
            server_default="11:45",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "restaurant_id", "customer_id", name="uq_recurring_message_customer"
        ),
    )
    op.create_index(
        op.f("ix_recurring_message_state_restaurant_id"),
        "recurring_message_state",
        ["restaurant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recurring_message_state_customer_id"),
        "recurring_message_state",
        ["customer_id"],
        unique=False,
    )

    op.create_table(
        "marketing_automation_sends",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("automation_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["automation_id"], ["marketing_automations.id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id", "customer_id", name="uq_marketing_automation_send"
        ),
    )
    op.create_index(
        op.f("ix_marketing_automation_sends_restaurant_id"),
        "marketing_automation_sends",
        ["restaurant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_marketing_automation_sends_automation_id"),
        "marketing_automation_sends",
        ["automation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_marketing_automation_sends_customer_id"),
        "marketing_automation_sends",
        ["customer_id"],
        unique=False,
    )

    for table in (
        "marketing_automations",
        "recurring_message_state",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for table in ("recurring_message_state", "marketing_automations"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    op.drop_table("marketing_automation_sends")
    op.drop_table("recurring_message_state")
    op.drop_table("marketing_automations")