"""add lottery_draw_triggered to notification_type_enum

Revision ID: c7f2a4d8e1b5
Revises: bfadb696c92a
Create Date: 2026-09-22 00:00:00.000000

A new producer (concert_service.notify_managers_of_draw_trigger, called from
the lottery-draw router the moment a manager presses "draw") needs an event
type for "a draw was just scheduled for this concert" — distinct from
lottery_result, which fires later, per-entry, once the async draw actually
completes. Carries concert_id, same as event_reminder. One concern: only the
enum gains a member, nothing else about `notifications` changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f2a4d8e1b5'
down_revision: Union[str, Sequence[str], None] = 'bfadb696c92a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE is itself idempotent via IF NOT EXISTS (PG9.6+)
    # and, unlike CREATE TYPE, has no "duplicate_object" exception to catch —
    # so this doesn't need the DO $$ ... EXCEPTION wrapper the enum-creation
    # migrations use. Safe to run inside Alembic's transaction on PG12+ as
    # long as the new value isn't read in the same transaction, which it
    # isn't here.
    op.execute(sa.text("ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS 'lottery_draw_triggered'"))


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — removing an enum member
    # requires rebuilding the type (rename old, create new, cast every
    # column, drop old), which isn't worth it for a downgrade path on a
    # portfolio project. Left as a documented no-op, same tradeoff this
    # repo already accepts elsewhere for one-way schema moves.
    pass
