"""merge floor-plan/audit branch into main line

Revision ID: e1c23230b540
Revises: d4e5f6a7b8c9, u4v5w6x7y8z9
Create Date: 2026-07-23 13:45:02.805533

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1c23230b540'
down_revision: Union[str, Sequence[str], None] = ('d4e5f6a7b8c9', 'u4v5w6x7y8z9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
