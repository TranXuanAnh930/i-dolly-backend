"""make payment.order_id nullable

Revision ID: b75496fd203e
Revises: 133d9b4f9d17
Create Date: 2026-09-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b75496fd203e'
down_revision: Union[str, Sequence[str], None] = '133d9b4f9d17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A ticket purchase needs a Payment row too, but tickets.payment_id already
# points *from* tickets at payment.id — payment never needed a column
# pointing back at tickets, only order_id needs to stop being mandatory so a
# ticket-only payment (order_id left null) is a valid row. See
# app/services/payment_service.create_ticket_payment.


def upgrade() -> None:
    op.alter_column('payment', 'order_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True)


def downgrade() -> None:
    op.alter_column('payment', 'order_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False)
