"""branch-scoped staff login: store_code / location_uuid / staff_code

Staff previously signed in with the platform-wide ``staff_members.id``, resolved
without any restaurant filter. This adds the branch key the terminal supplies
(``store_code`` / ``location_uuid``) and the per-restaurant staff number
(``staff_code``) so a login can only ever resolve inside one restaurant.

Revision ID: a8b9c0d1e2f3
Revises: 2e39bb241ffa

Chained onto 2e39bb241ffa because that is the revision the database is actually
stamped at. The repo carries 15 unmerged heads from before this change, so
picking any other head would make alembic replay a chain that is already applied
physically but never recorded.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "2e39bb241ffa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Kept in sync with app.identity.models.STORE_CODE_ALPHABET (no O/0, no I/1).
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_LENGTH = 8


def _backfill_store_identity() -> None:
    """Give every existing restaurant a unique code/uuid.

    Generated in Python rather than SQL so this does not depend on pgcrypto being
    installed, and so the alphabet matches the application's exactly.
    """
    import secrets
    import uuid as _uuid

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM restaurants")).fetchall()
    used: set[str] = set()
    for (rid,) in rows:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
        while code in used:
            code = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
        used.add(code)
        conn.execute(
            sa.text(
                "UPDATE restaurants SET store_code = :c, location_uuid = :u WHERE id = :i"
            ),
            {"c": code, "u": str(_uuid.uuid4()), "i": rid},
        )


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("location_uuid", sa.String(36), nullable=True))
    op.add_column("restaurants", sa.Column("store_code", sa.String(16), nullable=True))
    _backfill_store_identity()
    op.alter_column("restaurants", "location_uuid", nullable=False)
    op.alter_column("restaurants", "store_code", nullable=False)
    op.create_index(
        "ix_restaurants_location_uuid", "restaurants", ["location_uuid"], unique=True
    )
    op.create_index("ix_restaurants_store_code", "restaurants", ["store_code"], unique=True)

    op.add_column("staff_members", sa.Column("staff_code", sa.Integer(), nullable=True))
    # Number existing staff 1..N within each restaurant, oldest first, so the
    # numbers people are handed match hire order.
    op.execute(
        """
        UPDATE staff_members s
           SET staff_code = n.rn
          FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY restaurant_id ORDER BY id
                       ) AS rn
                  FROM staff_members
               ) n
         WHERE s.id = n.id
        """
    )
    op.create_unique_constraint(
        "uq_staff_code_per_restaurant", "staff_members", ["restaurant_id", "staff_code"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_staff_code_per_restaurant", "staff_members", type_="unique")
    op.drop_column("staff_members", "staff_code")
    op.drop_index("ix_restaurants_store_code", table_name="restaurants")
    op.drop_index("ix_restaurants_location_uuid", table_name="restaurants")
    op.drop_column("restaurants", "store_code")
    op.drop_column("restaurants", "location_uuid")
