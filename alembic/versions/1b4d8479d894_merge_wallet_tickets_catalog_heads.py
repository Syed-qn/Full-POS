"""merge wallet/tickets + catalog heads

Revision ID: 1b4d8479d894
Revises: f1a2b3c4d5e6, f3c4d5e6a7b8
Create Date: 2026-06-29 10:01:36.489901

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b4d8479d894'
down_revision: Union[str, Sequence[str], None] = ('f1a2b3c4d5e6', 'f3c4d5e6a7b8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
