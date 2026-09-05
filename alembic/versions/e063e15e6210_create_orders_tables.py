"""create new tables

Revision ID: e063e15e6210
Revises: cc69b18aa506
Create Date: 2026-01-22 18:04:27.929156

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e063e15e6210'
down_revision: Union[str, Sequence[str], None] = '57a47bc38338'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shipping_address_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("shipping_addresses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_price", sa.Float, nullable=False),
        sa.Column("status", sa.Enum("pending", "confirmed", "cancelled", name="order_status_enum"), server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    )

def downgrade() -> None:
    op.drop_table("orders")
