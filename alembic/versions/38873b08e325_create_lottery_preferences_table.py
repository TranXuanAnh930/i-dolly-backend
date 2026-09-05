"""create lottery_preferences table

Revision ID: 38873b08e325
Revises: fcea6e36cede
Create Date: 2026-09-04 15:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '38873b08e325'
down_revision: Union[str, Sequence[str], None] = 'fcea6e36cede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lottery_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "concert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticket_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint("chk_lottery_preferences_rank", "lottery_preferences", "rank > 0")
    op.create_unique_constraint(
        "uq_lottery_preferences_rank", "lottery_preferences", ["concert_id", "user_id", "rank"]
    )
    op.create_unique_constraint(
        "uq_lottery_preferences_tier", "lottery_preferences", ["concert_id", "user_id", "ticket_type_id"]
    )
    op.create_index("ix_lottery_preferences_user_id", "lottery_preferences", ["user_id"])

    # -------------------------------------------------------------------
    # DB-level guarantee that ticket_type_id actually belongs to concert_id
    # — without this, a mismatched row wouldn't error, it would just
    # silently never be considered by the draw job (database-design.md
    # §3.11/§6).
    # -------------------------------------------------------------------
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_require_ticket_type_matches_concert() RETURNS TRIGGER AS $$
        DECLARE
            actual_concert_id UUID;
        BEGIN
            SELECT concert_id INTO actual_concert_id
            FROM ticket_types
            WHERE id = NEW.ticket_type_id;

            IF actual_concert_id IS DISTINCT FROM NEW.concert_id THEN
                RAISE EXCEPTION 'lottery_preferences.ticket_type_id=% belongs to concert_id=%, not concert_id=% given on this row',
                    NEW.ticket_type_id, actual_concert_id, NEW.concert_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_lottery_preferences_ticket_type_concert
            BEFORE INSERT OR UPDATE OF concert_id, ticket_type_id ON lottery_preferences
            FOR EACH ROW EXECUTE FUNCTION fn_require_ticket_type_matches_concert();
        """
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_lottery_preferences_ticket_type_concert ON lottery_preferences"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_require_ticket_type_matches_concert()"))
    op.drop_table("lottery_preferences")
