"""products.category_id: ON DELETE CASCADE -> RESTRICT

Revision ID: c5e9a3b7d1f6
Revises: b3d7f1a5c9e4
Create Date: 2026-11-14 00:00:02.000000

With CASCADE, deleting a category deleted every product in it, and through them their order lines.
A category that still has products can no longer be deleted; CategoryService.delete_category
checks first, and this is the backstop.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5e9a3b7d1f6'
down_revision: Union[str, Sequence[str], None] = 'b3d7f1a5c9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('products_category_id_fkey', 'products', type_='foreignkey')
    op.create_foreign_key(
        'products_category_id_fkey', 'products', 'categories', ['category_id'], ['id'],
        onupdate='CASCADE', ondelete='RESTRICT',
    )


def downgrade() -> None:
    op.drop_constraint('products_category_id_fkey', 'products', type_='foreignkey')
    op.create_foreign_key(
        'products_category_id_fkey', 'products', 'categories', ['category_id'], ['id'],
        onupdate='CASCADE', ondelete='CASCADE',
    )
