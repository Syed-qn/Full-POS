"""pg_trgm_name_normalized

Revision ID: e99f4e761d39
Revises: 65800d534af2
Create Date: 2026-06-06 09:41:02.420500

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e99f4e761d39'
down_revision: Union[str, Sequence[str], None] = '65800d534af2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.add_column("dishes", sa.Column("name_normalized", sa.String(256), nullable=True))
    op.execute("""
        UPDATE dishes SET name_normalized = lower(regexp_replace(name, '[^a-zA-Z0-9 ]', '', 'g'))
        WHERE name_normalized IS NULL;
    """)
    op.execute("""
        CREATE INDEX ix_dishes_name_normalized_trgm
        ON dishes USING gin (name_normalized gin_trgm_ops);
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_dishes_name_normalized_trgm;")
    op.drop_column("dishes", "name_normalized")
