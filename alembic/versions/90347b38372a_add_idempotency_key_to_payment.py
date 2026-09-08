"""add idempotency_key to payment

Revision ID: 90347b38372a
Revises: 3ddc785cf8be
Create Date: 2026-09-08 21:48:17.291280

"""
from typing import Sequence, Union

from alembic import op

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '90347b38372a'
down_revision: Union[str, Sequence[str], None] = '3ddc785cf8be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payment', sa.Column('idempotency_key', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint('uq_payment_idempotency_key', 'payment', ['idempotency_key'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_payment_idempotency_key', 'payment', type_='unique')
    op.drop_column('payment', 'idempotency_key')
