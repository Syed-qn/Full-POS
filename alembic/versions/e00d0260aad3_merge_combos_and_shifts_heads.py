"""merge combos and shifts heads

Revision ID: e00d0260aad3
Revises: e794d12a05a8, 324ef2b2bb9b
Create Date: 2026-07-07 20:46:57.591398

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e00d0260aad3'
down_revision: Union[str, Sequence[str], None] = ('e794d12a05a8', '324ef2b2bb9b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
