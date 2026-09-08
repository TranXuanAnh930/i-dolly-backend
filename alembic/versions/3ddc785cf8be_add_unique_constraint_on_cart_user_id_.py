"""add unique constraint on cart user_id product_id

Revision ID: 3ddc785cf8be
Revises: 3e99ddf2945c
Create Date: 2026-09-08 20:19:05.972611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3ddc785cf8be'
down_revision: Union[str, Sequence[str], None] = '3e99ddf2945c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint('uq_cart_user_id_product_id', 'cart', ['user_id', 'product_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_cart_user_id_product_id', 'cart', type_='unique')
