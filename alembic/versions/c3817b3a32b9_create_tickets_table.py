"""create tickets table

Revision ID: c3817b3a32b9
Revises: f15a9003ac94
Create Date: 2026-09-04 15:01:45.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  


# revision identifiers, used by Alembic.
revision: str = 'c3817b3a32b9'
down_revision: Union[str, Sequence[str], None] = 'f15a9003ac94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ticket_status_enum = postgresql.ENUM(
    "reserved", "pending_payment", "paid", "cancelled", "expired", "used",
    name="ticket_status_enum",
    create_type=False
)


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
            CREATE TYPE ticket_status_enum AS ENUM ('reserved', 'pending_payment', 'paid', 'cancelled', 'expired', 'used');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "ticket_type_id",
            sa.Integer(),
            sa.ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        # null = directly purchased, no lottery involved.
        sa.Column(
            "lottery_entry_id",
            sa.Integer(),
            sa.ForeignKey("lottery_entries.id", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "payment_id",
            sa.Integer(),
            sa.ForeignKey("payment.id", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", ticket_status_enum, nullable=False, server_default="reserved"),
        sa.Column("issued_code", sa.VARCHAR(), nullable=True, unique=True),
        sa.Column(
            "reserved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("payment_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            server_onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_tickets_ticket_type_id", "tickets", ["ticket_type_id"])
    op.create_index("ix_tickets_user_id", "tickets", ["user_id"])

    # -------------------------------------------------------------------
    # Hard cap, as a BACKSTOP (not the primary mechanism — the draw job
    # should never actually try this): at most one LIVE ticket per user per
    # concert, regardless of tier or how it was obtained. A cancelled/
    # expired ticket doesn't count against the cap (database-design.md
    # §3.14).
    # -------------------------------------------------------------------
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_enforce_one_ticket_per_concert() RETURNS TRIGGER AS $$
        DECLARE
            target_concert_id INTEGER;
            existing_live_tickets INTEGER;
        BEGIN
            SELECT c.id INTO target_concert_id
            FROM ticket_types tt JOIN concerts c ON c.id = tt.concert_id
            WHERE tt.id = NEW.ticket_type_id;

            SELECT COUNT(*) INTO existing_live_tickets
            FROM tickets t JOIN ticket_types tt ON tt.id = t.ticket_type_id
            WHERE t.user_id = NEW.user_id
              AND tt.concert_id = target_concert_id
              AND t.status IN ('reserved', 'pending_payment', 'paid', 'used');

            IF existing_live_tickets > 0 THEN
                RAISE EXCEPTION 'user_id=% already holds a live ticket for concert_id=% — only one ticket per person per concert (lottery or direct) is allowed',
                    NEW.user_id, target_concert_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_tickets_one_per_concert
            BEFORE INSERT ON tickets
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_one_ticket_per_concert();
        """
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_tickets_one_per_concert ON tickets"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_enforce_one_ticket_per_concert()"))
    op.drop_index("ix_tickets_user_id", table_name="tickets")
    op.drop_index("ix_tickets_ticket_type_id", table_name="tickets")
    op.drop_table("tickets")
    op.execute(sa.text("DROP TYPE IF EXISTS ticket_status_enum"))
