"""make products.category_id NOT NULL

Revision ID: 71b1b0443c96
Revises: ecf1f2ed802f
Create Date: 2026-09-04 13:25:56.088421

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71b1b0443c96'
down_revision: Union[str, Sequence[str], None] = 'ecf1f2ed802f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# database-design.md Section 6/7.1: tightening products.category_id to NOT
# NULL was explicitly deferred until there was something to backfill
# uncategorized products TO. That "something" is the 'Merch' category — the
# marketplace design's catch-all bucket (schema.sql Section 4a) — seeded here
# ONLY if it doesn't already exist, so this migration is safe to run whether
# or not a 'Merch' row already got created by some other path. The later
# categories-normalization migration (is_resale_capped, Album/Single/EP/
# Lightstick, schema.sql Section 4a) reuses this same row by name — it
# INSERTs the other four and UPDATEs is_resale_capped on all five, rather
# than re-inserting 'Merch'.
FALLBACK_CATEGORY_NAME = "Merch"


def upgrade() -> None:
    bind = op.get_bind()

    # Idempotent: only insert if a category with this name doesn't already
    # exist (categories.name is UNIQUE — see CLAUDE.md item 13 — so this could
    # also be an INSERT ... ON CONFLICT DO NOTHING; written as SELECT-then-
    # INSERT to avoid depending on the naming of that unique constraint).
    existing = bind.execute(
        sa.text("SELECT id FROM categories WHERE name = :name"),
        {"name": FALLBACK_CATEGORY_NAME},
    ).fetchone()

    if existing is None:
        result = bind.execute(
            sa.text("INSERT INTO categories (name) VALUES (:name) RETURNING id"),
            {"name": FALLBACK_CATEGORY_NAME},
        )
        fallback_id = result.fetchone()[0]
    else:
        fallback_id = existing[0]

    # Backfill: every existing product with no category becomes 'Merch'.
    op.execute(
        sa.text("UPDATE products SET category_id = :fid WHERE category_id IS NULL").bindparams(
            fid=fallback_id
        )
    )

    op.alter_column("products", "category_id", nullable=False)


def downgrade() -> None:
    # Reversible in the schema sense (column goes back to nullable); the
    # 'Merch' category row and the backfilled category_id values are
    # deliberately NOT reverted — there's no way to know which rows were
    # NULL before this migration ran, and leaving products categorized is
    # harmless, unlike guessing which ones to null back out.
    op.alter_column("products", "category_id", nullable=True)
