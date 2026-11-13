"""orders_items.product_id: ON DELETE CASCADE -> RESTRICT

Revision ID: b3d7f1a5c9e4
Revises: a1c5e7f9b3d2
Create Date: 2026-11-14 00:00:01.000000

With CASCADE, deleting a product silently deleted its line from every past order, leaving orders
whose total no longer matched their items. Products are soft-deleted now; RESTRICT is the backstop
that makes the database refuse to delete a product that has ever been ordered.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3d7f1a5c9e4'
down_revision: Union[str, Sequence[str], None] = 'a1c5e7f9b3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('orders_items_product_id_fkey', 'orders_items', type_='foreignkey')
    op.create_foreign_key(
        'orders_items_product_id_fkey', 'orders_items', 'products', ['product_id'], ['id'], ondelete='RESTRICT'
    )


def downgrade() -> None:
    op.drop_constraint('orders_items_product_id_fkey', 'orders_items', type_='foreignkey')
    op.create_foreign_key(
        'orders_items_product_id_fkey', 'orders_items', 'products', ['product_id'], ['id'], ondelete='CASCADE'
    )
