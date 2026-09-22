"""add lottery_draw_failed to notification_type_enum

Revision ID: d3a9e5f1c8b7
Revises: c7f2a4d8e1b5
Create Date: 2026-09-22 00:00:00.000000

draw_lottery_task (app/tasks/lottery.py) previously had no error handling at
all — an exception mid-draw (e.g. the BadRequestError from a double-click/
cross-manager race on an already-closed campaign) died silently in the
Celery worker with zero user-facing signal. The task-level fix (in progress,
handled outside this migration) needs an event type for "a draw was
scheduled but did not complete" to notify the concert's own managers,
distinct from lottery_draw_triggered (fires at schedule time) and
lottery_result (fires per-entry, only on a *successful* draw). Carries
concert_id, same shape as lottery_draw_triggered. One concern: only the enum
gains a member, nothing else about `notifications` changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3a9e5f1c8b7'
down_revision: Union[str, Sequence[str], None] = 'c7f2a4d8e1b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE is itself idempotent via IF NOT EXISTS (PG9.6+)
    # and, unlike CREATE TYPE, has no "duplicate_object" exception to catch —
    # so this doesn't need the DO $$ ... EXCEPTION wrapper the enum-creation
    # migrations use. Safe to run inside Alembic's transaction on PG12+ as
    # long as the new value isn't read in the same transaction, which it
    # isn't here.
    op.execute(sa.text("ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS 'lottery_draw_failed'"))


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — removing an enum member
    # requires rebuilding the type (rename old, create new, cast every
    # column, drop old), which isn't worth it for a downgrade path on a
    # portfolio project. Left as a documented no-op, same tradeoff this
    # repo already accepts elsewhere for one-way schema moves.
    pass
