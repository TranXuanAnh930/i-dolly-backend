"""add order_shipped to notification_type_enum

Revision ID: f1a7c3e9b5d2
Revises: e4f8b2a6c9d1
Create Date: 2026-09-24 00:00:00.000000

New producer: OrderService.ship_order, fired when a manager marks an order shipped
(PATCH /order/{order_id}/ship). Carries order_id, an FK the notifications table already has (same
one order_confirmation uses) — no new column needed, just the enum member.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a7c3e9b5d2'
down_revision: Union[str, Sequence[str], None] = 'e4f8b2a6c9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE is itself idempotent via IF NOT EXISTS (PG9.6+)
    # and, unlike CREATE TYPE, has no "duplicate_object" exception to catch —
    # so this doesn't need the DO $$ ... EXCEPTION wrapper the enum-creation
    # migrations use. Safe to run inside Alembic's transaction on PG12+ as
    # long as the new value isn't read in the same transaction, which it
    # isn't here.
    op.execute(sa.text("ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS 'order_shipped'"))


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — removing an enum member
    # requires rebuilding the type (rename old, create new, cast every
    # column, drop old), which isn't worth it for a downgrade path on a
    # portfolio project. Left as a documented no-op, same tradeoff this
    # repo already accepts elsewhere for one-way schema moves.
    pass
