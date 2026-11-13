"""add is_active to products

Revision ID: a1c5e7f9b3d2
Revises: d4a7c9e2f1b5
Create Date: 2026-11-14 00:00:00.000000

Soft-delete flag, the same shape as groups.is_active and idols.is_active. Deleting a product now
clears this flag instead of removing the row, so order lines that reference the product survive.
Existing rows default to active.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c5e7f9b3d2'
down_revision: Union[str, Sequence[str], None] = 'd4a7c9e2f1b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    op.drop_column('products', 'is_active')
