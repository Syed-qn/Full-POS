"""merge menu/kds/ordering/dispatch/inventory heads

Revision ID: 5c8c8d3b2c85
Revises: 133d88b69631, d62b4e084827, u2v3w4x5y6z7, w4x5y6z7a8b9, x5y6z7a8b9c0
Create Date: 2026-07-08 22:39:56.146448

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c8c8d3b2c85'
down_revision: Union[str, Sequence[str], None] = ('133d88b69631', 'd62b4e084827', 'u2v3w4x5y6z7', 'w4x5y6z7a8b9', 'x5y6z7a8b9c0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
