"""add password_reset to notification_type_enum

Revision ID: a3f7c9e2b6d4
Revises: f8a3c1d9e4b2
Create Date: 2026-09-13 00:00:00.000000

The notification producer wiring (order/ticket/lottery/password-reset flows
now insert rows, see notification_service.create_notification) needs a
`password_reset` event that carries no order/ticket/lottery_entry/concert FK
at all — it's about the user alone, unlike every other existing type. One
concern: only the enum gains a member, nothing else about `notifications`
changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f7c9e2b6d4'
down_revision: Union[str, Sequence[str], None] = 'f8a3c1d9e4b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE is itself idempotent via IF NOT EXISTS (PG9.6+)
    # and, unlike CREATE TYPE, has no "duplicate_object" exception to catch —
    # so this doesn't need the DO $$ ... EXCEPTION wrapper the enum-creation
    # migrations use. Safe to run inside Alembic's transaction on PG12+ as
    # long as the new value isn't read in the same transaction, which it
    # isn't here.
    op.execute(sa.text("ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS 'password_reset'"))


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — removing an enum member
    # requires rebuilding the type (rename old, create new, cast every
    # column, drop old), which isn't worth it for a downgrade path on a
    # portfolio project. Left as a documented no-op, same tradeoff this
    # repo already accepts elsewhere for one-way schema moves.
    pass
