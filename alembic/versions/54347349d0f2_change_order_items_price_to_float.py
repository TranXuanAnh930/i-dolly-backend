"""change orders_items.price to Float

Revision ID: 54347349d0f2
Revises: e8b4a1f0c5d7
Create Date: 2026-09-19 00:00:00.000000

orders_items.price was Integer while products.price is Float — a tax-inclusive
line price (order_service.checkout's with_tax(item.price)) truncated to a
whole number on every order, silently understating order-history totals for
any non-integer price. INTEGER -> FLOAT widens without data loss; no backfill
needed. One concern: only this column's type changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54347349d0f2'
down_revision: Union[str, Sequence[str], None] = 'e8b4a1f0c5d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("orders_items", "price", type_=sa.Float(), existing_type=sa.Integer(), existing_nullable=False)


def downgrade() -> None:
    # Narrowing back to Integer truncates any fractional price written since the upgrade —
    # accepted, same one-way-street reasoning as every other narrowing downgrade in this chain.
    op.alter_column("orders_items", "price", type_=sa.Integer(), existing_type=sa.Float(), existing_nullable=False)
