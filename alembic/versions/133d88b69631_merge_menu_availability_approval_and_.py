"""merge menu availability/approval and dish price rules heads

Revision ID: 133d88b69631
Revises: e404fdae14c7, v3w4x5y6z7a8
Create Date: 2026-07-08 21:37:09.285684

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '133d88b69631'
down_revision: Union[str, Sequence[str], None] = ('e404fdae14c7', 'v3w4x5y6z7a8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
