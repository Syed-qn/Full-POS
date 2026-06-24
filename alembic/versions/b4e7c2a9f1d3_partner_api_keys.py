"""partner_api_keys: API keys for partner (POS) read-only data pulls

Per-restaurant API keys stored as SHA-256 hashes (plaintext never persisted).
TimestampMixin table, so it gets the standard BEFORE UPDATE trg_*_updated_at
trigger (the set_updated_at() function already exists from an earlier migration).

Revision ID: b4e7c2a9f1d3
Revises: c9f2a1b4d6e8
Create Date: 2026-06-24
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4e7c2a9f1d3"
down_revision: Union[str, Sequence[str], None] = "c9f2a1b4d6e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "partner_api_keys",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("key_prefix", sa.String(length=20), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_partner_api_keys_restaurant_id", "partner_api_keys", ["restaurant_id"]
    )
    op.create_index(
        "ix_partner_api_keys_key_hash", "partner_api_keys", ["key_hash"], unique=True
    )
    op.execute(
        "CREATE TRIGGER trg_partner_api_keys_updated_at BEFORE UPDATE ON partner_api_keys "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_partner_api_keys_updated_at ON partner_api_keys;")
    op.drop_index("ix_partner_api_keys_key_hash", table_name="partner_api_keys")
    op.drop_index("ix_partner_api_keys_restaurant_id", table_name="partner_api_keys")
    op.drop_table("partner_api_keys")
