"""create notifications table

Revision ID: df79d71c6a2c
Revises: 10f9dfa05636
Create Date: 2026-09-05 22:57:41.229176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'df79d71c6a2c'
down_revision: Union[str, Sequence[str], None] = '10f9dfa05636'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

notification_type_enum = postgresql.ENUM(
    "order_confirmation",
    "ticket_confirmation",
    "lottery_registered",
    "lottery_result",
    "lottery_payment_reminder",
    "lottery_payment_confirmation",
    "event_reminder",
    name="notification_type_enum",
    create_type=False,
)
notification_status_enum = postgresql.ENUM(
    "pending", "sent", "failed", name="notification_status_enum", create_type=False
)


# Same idempotent DO $$ ... EXCEPTION WHEN duplicate_object pattern as every
# other enum in this repo (see f15a9003ac94) instead of checkfirst=True.
def upgrade() -> None:
    op.execute(sa.text(
        """
        DO $$ BEGIN
            CREATE TYPE notification_type_enum AS ENUM (
                'order_confirmation',
                'ticket_confirmation',
                'lottery_registered',
                'lottery_result',
                'lottery_payment_reminder',
                'lottery_payment_confirmation',
                'event_reminder'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))
    op.execute(sa.text(
        """
        DO $$ BEGIN
            CREATE TYPE notification_status_enum AS ENUM ('pending', 'sent', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    # One row per notification event for one user. Which of order_id/ticket_id/
    # lottery_entry_id/concert_id is populated depends on `type` (e.g.
    # order_confirmation -> order_id, event_reminder -> concert_id) — exactly
    # one is expected to be set per row, but that's ordinary cross-table
    # validation (database-design.md §3.4-style), not a money/fairness
    # invariant, so per this repo's trigger criteria (database-design.md §4.1)
    # it's a service-layer check when notifications get written, not a DB
    # CHECK/trigger here.
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", notification_type_enum, nullable=False),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "lottery_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lottery_entries.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "concert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=True,
        ),
        # Send-log side (the future Celery/SendGrid task updates these).
        sa.Column("status", notification_status_enum, nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        # In-app feed side (a fan viewing/dismissing their notification list).
        sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_order_id", "notifications", ["order_id"])
    op.create_index("ix_notifications_ticket_id", "notifications", ["ticket_id"])
    op.create_index("ix_notifications_lottery_entry_id", "notifications", ["lottery_entry_id"])
    op.create_index("ix_notifications_concert_id", "notifications", ["concert_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_concert_id", table_name="notifications")
    op.drop_index("ix_notifications_lottery_entry_id", table_name="notifications")
    op.drop_index("ix_notifications_ticket_id", table_name="notifications")
    op.drop_index("ix_notifications_order_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.execute(sa.text("DROP TYPE IF EXISTS notification_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS notification_type_enum"))
