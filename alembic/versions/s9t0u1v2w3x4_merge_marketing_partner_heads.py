"""merge marketing automations + partner api key heads

Revision ID: s9t0u1v2w3x4
Revises: q0d1e2f3g4h5, r8s9t0u1v2w3
Create Date: 2026-07-03 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s9t0u1v2w3x4"
down_revision: Union[str, Sequence[str], None] = ("q0d1e2f3g4h5", "r8s9t0u1v2w3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass