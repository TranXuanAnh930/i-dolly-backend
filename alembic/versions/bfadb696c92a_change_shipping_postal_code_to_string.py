"""change shipping_addresses.postal_code to String

Revision ID: bfadb696c92a
Revises: 54347349d0f2
Create Date: 2026-09-19 00:00:00.000001

postal_code was Integer, which rejects any alphanumeric postal code (UK, Canada,
Japan, etc.) and drops a leading zero on the ones that are all-digits. Widening
to VARCHAR needs an explicit USING cast — Postgres won't implicitly convert
INTEGER -> VARCHAR the way it does the reverse. One concern: only this column's
type changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfadb696c92a'
down_revision: Union[str, Sequence[str], None] = '54347349d0f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "shipping_addresses", "postal_code",
        type_=sa.String(), existing_type=sa.Integer(), existing_nullable=False,
        postgresql_using="postal_code::varchar",
    )


def downgrade() -> None:
    # Narrowing back to Integer fails outright if any alphanumeric code was written since the
    # upgrade — deliberately not caught here; that data loss should be visible, not silently
    # dropped rows.
    op.alter_column(
        "shipping_addresses", "postal_code",
        type_=sa.Integer(), existing_type=sa.String(), existing_nullable=False,
        postgresql_using="postal_code::integer",
    )
