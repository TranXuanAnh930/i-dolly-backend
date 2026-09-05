"""create lottery_entries table

Revision ID: f15a9003ac94
Revises: 5306320d754d
Create Date: 2026-09-04 15:01:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  

# revision identifiers, used by Alembic.
revision: str = 'f15a9003ac94'
down_revision: Union[str, Sequence[str], None] = '5306320d754d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

lottery_entry_status_enum = postgresql.ENUM("pending", "won", "lost", "expired", name="lottery_entry_status_enum", create_type=False)


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
            CREATE TYPE lottery_entry_status_enum AS ENUM ('pending', 'won', 'lost', 'expired');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    # One row = one direct application to one campaign's lottery — no order/
    # payment linkage at all (database-design.md §3.13's scope change).
    # NO UNIQUE(campaign_id, user_id): the cap now lives on
    # lottery_campaigns.max_entries_per_user, enforced by the trigger below
    # instead of a hard structural constraint.
    op.create_table(
        "lottery_entries",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("lottery_campaigns.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", lottery_entry_status_enum, nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("drawn_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_lottery_entries_campaign_id", "lottery_entries", ["campaign_id"])
    op.create_index("ix_lottery_entries_user_id", "lottery_entries", ["user_id"])

    # -------------------------------------------------------------------
    # Enforces lottery_campaigns.max_entries_per_user (database-design.md
    # §3.13/§6) — a money/fairness invariant (a fan getting more shots at a
    # draw than the campaign allows), same bar as every other trigger here.
    # -------------------------------------------------------------------
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_enforce_lottery_entry_cap() RETURNS TRIGGER AS $$
        DECLARE
            max_allowed INTEGER;
            existing_count INTEGER;
        BEGIN
            SELECT max_entries_per_user INTO max_allowed
            FROM lottery_campaigns
            WHERE id = NEW.campaign_id;

            SELECT COUNT(*) INTO existing_count
            FROM lottery_entries
            WHERE campaign_id = NEW.campaign_id AND user_id = NEW.user_id;

            IF existing_count >= max_allowed THEN
                RAISE EXCEPTION 'user_id=% already has % entries for campaign_id=% (max_entries_per_user=%)',
                    NEW.user_id, existing_count, NEW.campaign_id, max_allowed;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_lottery_entries_cap
            BEFORE INSERT ON lottery_entries
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_lottery_entry_cap();
        """
    ))

    # -------------------------------------------------------------------
    # Hard prerequisite: a fan can't be entered into a tier's lottery unless
    # they've already ranked that tier via lottery_preferences for this
    # concert (database-design.md §5.2).
    # -------------------------------------------------------------------
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_require_lottery_preference() RETURNS TRIGGER AS $$
        DECLARE
            target_ticket_type_id INTEGER;
            target_concert_id INTEGER;
            has_preference BOOLEAN;
        BEGIN
            SELECT lc.ticket_type_id, tt.concert_id
              INTO target_ticket_type_id, target_concert_id
            FROM lottery_campaigns lc
            JOIN ticket_types tt ON tt.id = lc.ticket_type_id
            WHERE lc.id = NEW.campaign_id;

            SELECT EXISTS(
                SELECT 1 FROM lottery_preferences
                WHERE concert_id = target_concert_id
                  AND user_id = NEW.user_id
                  AND ticket_type_id = target_ticket_type_id
            ) INTO has_preference;

            IF NOT has_preference THEN
                RAISE EXCEPTION 'user_id=% has not ranked ticket_type_id=% (concert_id=%) — set a lottery_preferences rank before entering that tier''s lottery',
                    NEW.user_id, target_ticket_type_id, target_concert_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_lottery_entries_require_preference
            BEFORE INSERT ON lottery_entries
            FOR EACH ROW EXECUTE FUNCTION fn_require_lottery_preference();
        """
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_lottery_entries_require_preference ON lottery_entries"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_require_lottery_preference()"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_lottery_entries_cap ON lottery_entries"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_enforce_lottery_entry_cap()"))
    op.drop_index("ix_lottery_entries_user_id", table_name="lottery_entries")
    op.drop_index("ix_lottery_entries_campaign_id", table_name="lottery_entries")
    op.drop_table("lottery_entries")
    op.execute(sa.text("DROP TYPE IF EXISTS lottery_entry_status_enum"))
