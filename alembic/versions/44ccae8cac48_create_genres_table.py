"""create genres table

Revision ID: 44ccae8cac48
Revises: 7c98b35ff6d2
Create Date: 2026-09-04 15:02:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '44ccae8cac48'
down_revision: Union[str, Sequence[str], None] = '7c98b35ff6d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Seed data — extend freely, same rationale as `positions`: an open-ended,
# growing list belongs in a table, not a Postgres enum.
SEED_GENRES = [
    "K-Pop", "Pop", "Dance", "Hip-Hop", "R&B", "Ballad",
    "Rock", "Electronic", "Acoustic", "City Pop",
]


def upgrade() -> None:
    op.create_table(
        "genres",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            index=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.VARCHAR(), nullable=False, unique=True),
    )

    genres = sa.table(
        "genres",
        sa.column("name", sa.VARCHAR()),
    )
    op.bulk_insert(genres, [{"name": name} for name in SEED_GENRES])


def downgrade() -> None:
    op.drop_table("genres")
