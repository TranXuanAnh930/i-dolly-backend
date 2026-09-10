"""make payment idempotency_key not null

Revision ID: 876977f26275
Revises: 90347b38372a
Create Date: 2026-09-08 22:24:54.431319

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '876977f26275'
down_revision: Union[str, Sequence[str], None] = '90347b38372a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(sa.text(
        "UPDATE payment SET idempotency_key = gen_random_uuid() WHERE idempotency_key IS NULL"
    ))
    op.alter_column('payment', 'idempotency_key', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('payment', 'idempotency_key', nullable=True)
