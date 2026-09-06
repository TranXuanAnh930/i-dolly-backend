"""add ticket_id to payment

Revision ID: 3e99ddf2945c
Revises: b75496fd203e
Create Date: 2026-09-06 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3e99ddf2945c'
down_revision: Union[str, Sequence[str], None] = 'b75496fd203e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# tickets.payment_id (added long before ticket checkout existed) only ever
# let you go ticket -> payment. Without a column pointing the other way,
# PaymentResponse/fetch_all_payments had no way to say what a ticket
# payment was *for* — a payment row with order_id=null and nothing else
# is untraceable without a reverse scan of tickets. See
# app/services/payment_service.create_ticket_payment.


def upgrade() -> None:
    op.add_column('payment', sa.Column('ticket_id', postgresql.UUID(as_uuid=True), nullable=True))
    # CASCADE, matching payment.order_id's own delete behavior on this same
    # table, rather than tickets.payment_id's SET NULL (a different FK, on
    # the other table, going the other direction).
    op.create_foreign_key(
        'payment_ticket_id_fkey', 'payment', 'tickets',
        ['ticket_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_payment_ticket_id', 'payment', ['ticket_id'])


def downgrade() -> None:
    op.drop_index('ix_payment_ticket_id', table_name='payment')
    op.drop_constraint('payment_ticket_id_fkey', 'payment', type_='foreignkey')
    op.drop_column('payment', 'ticket_id')
