"""create order_items  tables

Revision ID: 533da426d1db
Revises: cc69b18aa506
Create Date: 2026-01-22 18:28:36.375608

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '533da426d1db'
down_revision: Union[str, Sequence[str], None] = 'cc69b18aa506'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("price", sa.Integer, nullable=False)
    )


def downgrade() -> None:
    op.drop_table("orders_items")
