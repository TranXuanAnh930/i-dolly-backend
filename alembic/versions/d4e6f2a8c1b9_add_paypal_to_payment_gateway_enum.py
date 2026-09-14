"""add paypal to payment_gateway_enum

Revision ID: d4e6f2a8c1b9
Revises: a3f7c9e2b6d4
Create Date: 2026-09-15 00:00:00.000000

PaymentGateway.paypal already exists on the Python/Pydantic side
(app/schema/payment.py) and payment_service.py already branches on it, but
the Postgres enum backing payment.payment_gateway only ever had 'mock' —
writing a real paypal Payment row fails with "invalid input value for
enum" until this runs. One concern: only the enum gains a member, nothing
else about `payment` changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e6f2a8c1b9'
down_revision: Union[str, Sequence[str], None] = 'a3f7c9e2b6d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Same reasoning as a3f7c9e2b6d4 (password_reset -> notification_type_enum):
    # ADD VALUE IF NOT EXISTS is itself idempotent, no DO $$ ... EXCEPTION
    # wrapper needed the way CREATE TYPE requires.
    op.execute(sa.text("ALTER TYPE payment_gateway_enum ADD VALUE IF NOT EXISTS 'paypal'"))


def downgrade() -> None:
    # No ALTER TYPE ... DROP VALUE in Postgres — same documented one-way
    # tradeoff as a3f7c9e2b6d4, not worth a full type-rebuild for this.
    pass
