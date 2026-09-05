"""create lottery_campaigns table

Revision ID: 5306320d754d
Revises: 38873b08e325
Create Date: 2026-09-04 15:01:15.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  


# revision identifiers, used by Alembic.
revision: str = '5306320d754d'
down_revision: Union[str, Sequence[str], None] = '38873b08e325'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

campaign_status_enum = postgresql.ENUM("open", "drawn", "completed", "cancelled", name="campaign_status_enum", create_type=False)


# CORRECTION: previously `<enum>.create(bind, checkfirst=True)` — normally
# idempotent, but this Postgres instance ended up with the type object
# present without alembic_version recording this migration as applied
# (a prior interrupted/partial deploy attempt against this long-lived dev
# DB, most likely), which turned a routine restart into a permanent
# "type already exists" crash-loop. Switched to a `DO $$ ... EXCEPTION
# WHEN duplicate_object THEN NULL; END $$;` block — atomic (no separate
# check-then-create step to race or drift out of sync) and self-healing
# if the type is ever already present for any reason.
def upgrade() -> None:
    op.execute(sa.text(
        """
        DO $$ BEGIN
            CREATE TYPE campaign_status_enum AS ENUM ('open', 'drawn', 'completed', 'cancelled');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    op.create_table(
        "lottery_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "ticket_type_id",
            sa.Integer(),
            sa.ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draw_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_deadline_hours", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("status", campaign_status_enum, nullable=False, server_default="open"),
        # Data-driven relaxation knob (database-design.md §6/§3.12): a
        # per-campaign cap instead of a schema-level hard limit, so raising it
        # later is an UPDATE, not a migration. Default 1 keeps today's "one
        # entry per campaign, for now" behavior exactly as designed.
        sa.Column("max_entries_per_user", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "chk_lottery_campaigns_payment_deadline", "lottery_campaigns", "payment_deadline_hours > 0"
    )
    op.create_check_constraint(
        "chk_lottery_campaigns_max_entries", "lottery_campaigns", "max_entries_per_user > 0"
    )
    op.create_check_constraint(
        "chk_lottery_campaigns_window",
        "lottery_campaigns",
        "entry_end_at > entry_start_at AND draw_at >= entry_end_at",
    )
    op.create_index("ix_lottery_campaigns_ticket_type_id", "lottery_campaigns", ["ticket_type_id"])


def downgrade() -> None:
    op.drop_index("ix_lottery_campaigns_ticket_type_id", table_name="lottery_campaigns")
    op.drop_table("lottery_campaigns")
    op.execute(sa.text("DROP TYPE IF EXISTS campaign_status_enum"))
