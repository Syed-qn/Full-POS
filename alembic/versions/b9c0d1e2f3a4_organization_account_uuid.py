"""organizations.account_uuid — the account half of account+location

A pairing link carries account + location so a terminal states which business
AND which branch it belongs to. location_uuid already exists on restaurants;
this adds its counterpart on organizations.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("account_uuid", sa.String(36), nullable=True))
    # Generated in Python so this does not depend on pgcrypto being installed.
    import uuid as _uuid

    conn = op.get_bind()
    for (oid,) in conn.execute(sa.text("SELECT id FROM organizations")).fetchall():
        conn.execute(
            sa.text("UPDATE organizations SET account_uuid = :u WHERE id = :i"),
            {"u": str(_uuid.uuid4()), "i": oid},
        )
    op.alter_column("organizations", "account_uuid", nullable=False)
    op.create_index(
        "ix_organizations_account_uuid", "organizations", ["account_uuid"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_account_uuid", table_name="organizations")
    op.drop_column("organizations", "account_uuid")
