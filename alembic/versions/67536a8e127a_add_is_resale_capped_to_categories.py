"""add is_resale_capped to categories

Revision ID: 67536a8e127a
Revises: c3817b3a32b9
Create Date: 2026-09-04 15:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67536a8e127a'
down_revision: Union[str, Sequence[str], None] = 'c3817b3a32b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `categories.name` is already UNIQUE from the original migration
# (f2a3135a19da) — nothing to add for that here (database-design.md §4a).
# `is_resale_capped` is the actual change: default/seed `true` across the
# board — "cap all products on the marketplace" — not just Album/Single/EP/
# Lightstick. Data-driven rather than hardcoded in the trigger, so exempting
# a category later is an UPDATE, not a code change.


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("is_resale_capped", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    for name in ("Album", "Single", "EP", "Lightstick", "Merch"):
        # ON CONFLICT ... DO UPDATE, not DO NOTHING: 71b1b0443c96 (the earlier
        # products.category_id NOT NULL migration) already seeds a bare
        # 'Merch' row with no is_resale_capped opinion, since that column
        # didn't exist yet at that point in the chain. This makes sure that
        # pre-existing row picks up is_resale_capped=true too.
        op.execute(sa.text(
            "INSERT INTO categories (name, is_resale_capped) VALUES (:name, true) "
            "ON CONFLICT (name) DO UPDATE SET is_resale_capped = true"
        ).bindparams(name=name))


def downgrade() -> None:
    op.drop_column("categories", "is_resale_capped")
