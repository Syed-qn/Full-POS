"""okf_docs — Open Knowledge Format concept store for RAG grounding

Per-restaurant markdown+YAML concept docs (dish/policy/restaurant/customer/order)
with a pg_trgm GIN index on search_text for lexical retrieval.

Revision ID: b2d4f6a8c0e2
Revises: a1c2e3f4b5d6
Create Date: 2026-06-29
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2d4f6a8c0e2"
down_revision: Union[str, Sequence[str], None] = "a1c2e3f4b5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.create_table(
        "okf_docs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("frontmatter", postgresql.JSONB(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "kind", "slug", name="uq_okf_docs_rest_kind_slug"),
    )
    op.create_index("ix_okf_docs_restaurant_id", "okf_docs", ["restaurant_id"])
    op.create_index("ix_okf_docs_kind", "okf_docs", ["kind"])
    op.create_index("ix_okf_docs_entity_id", "okf_docs", ["entity_id"])
    op.create_index("ix_okf_docs_rest_kind", "okf_docs", ["restaurant_id", "kind"])
    op.execute(
        "CREATE INDEX ix_okf_docs_search_trgm ON okf_docs "
        "USING gin (search_text gin_trgm_ops);"
    )
    op.execute(
        "CREATE TRIGGER trg_okf_docs_updated_at BEFORE UPDATE ON okf_docs "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_okf_docs_updated_at ON okf_docs;")
    op.execute("DROP INDEX IF EXISTS ix_okf_docs_search_trgm;")
    op.drop_table("okf_docs")
