"""add pg_approval_url to payment

Revision ID: e8b4a1f0c5d7
Revises: d4e6f2a8c1b9
Create Date: 2026-09-13 00:00:00.000000

create_order()'s PayPal response carries the buyer-facing redirect link (the
"payer-action"/"approve" HATEOAS link) needed to send a fan to PayPal to
approve the payment, but nothing captured it — create_payment/
create_ticket_payment discarded the full response down to just ["id"]. This
column persists that URL alongside the pg_order_id it belongs to, so
PaymentResponse can hand it back to a frontend without re-deriving it. One
concern: only this new column, nothing else about `payment` changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b4a1f0c5d7'
down_revision: Union[str, Sequence[str], None] = 'd4e6f2a8c1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment", sa.Column("pg_approval_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("payment", "pg_approval_url")
