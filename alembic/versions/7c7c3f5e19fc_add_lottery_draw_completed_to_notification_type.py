"""add lottery_draw_completed to notification_type_enum

Revision ID: 7c7c3f5e19fc
Revises: d3a9e5f1c8b7
Create Date: 2026-09-23 02:30:26.000000

lottery_draw_service.draw_lottery had a triggered notification (fires when
the draw is scheduled) and a failed notification (fires if the Celery task
raises), but nothing for the actual happy path — a manager who wasn't
watching the concert's edit page when the draw finished (the frontend's own
poll loop, store/events/lotteryDraw.js, only surfaces success while that
page is open) had no persistent record that the draw ever completed, only
that it started. This adds the missing third state, symmetric with
lottery_draw_triggered/lottery_draw_failed — same shape, carries concert_id.
Only the enum gains a member, nothing else about `notifications` changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c7c3f5e19fc'
down_revision: Union[str, Sequence[str], None] = 'd3a9e5f1c8b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE is itself idempotent via IF NOT EXISTS (PG9.6+)
    # and, unlike CREATE TYPE, has no "duplicate_object" exception to catch —
    # so this doesn't need the DO $$ ... EXCEPTION wrapper the enum-creation
    # migrations use. Safe to run inside Alembic's transaction on PG12+ as
    # long as the new value isn't read in the same transaction, which it
    # isn't here.
    op.execute(sa.text("ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS 'lottery_draw_completed'"))


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — removing an enum member
    # requires rebuilding the type (rename old, create new, cast every
    # column, drop old), which isn't worth it for a downgrade path on a
    # portfolio project. Left as a documented no-op, same tradeoff this
    # repo already accepts elsewhere for one-way schema moves.
    pass
