"""create positions table

Revision ID: ecf1f2ed802f
Revises: 46c5f500e7bd
Create Date: 2026-09-04 13:05:21.551965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ecf1f2ed802f'
down_revision: Union[str, Sequence[str], None] = '46c5f500e7bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Seed data — extend freely, this is a lookup table, not an enum, precisely so
# a new position doesn't need a migration.
SEED_POSITIONS = [
    "Leader", "Main Vocalist", "Vocalist", "Lead Dancer", "Dancer",
    "Rapper", "Visual", "Center", "Maknae", "Guitarist", "Bassist",
    "Drummer", "Keyboardist", "Producer",
]


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.VARCHAR(), nullable=False, unique=True),
    )

    positions = sa.table(
        "positions",
        sa.column("name", sa.VARCHAR()),
    )
    op.bulk_insert(positions, [{"name": name} for name in SEED_POSITIONS])


def downgrade() -> None:
    op.drop_table("positions")
