"""updated_at_triggers_audit_composite_index

Revision ID: f6764ecf8b8d
Revises: ea5ef5651223
Create Date: 2026-06-06 05:00:56.670491

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6764ecf8b8d'
down_revision: Union[str, Sequence[str], None] = 'ea5ef5651223'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END;
        $$ LANGUAGE plpgsql;
        """
    )
    for t in ("audit_log", "restaurants", "riders"):
        op.execute(
            f"CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )
    op.create_index(
        "ix_audit_log_restaurant_entity",
        "audit_log",
        ["restaurant_id", "entity", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_restaurant_entity", table_name="audit_log")
    for t in ("audit_log", "restaurants", "riders"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{t}_updated_at ON {t};")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
