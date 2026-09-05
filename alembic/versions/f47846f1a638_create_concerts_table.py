"""create concerts table

Revision ID: f47846f1a638
Revises: 965f5718222d
Create Date: 2026-09-04 15:00:15.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  


# revision identifiers, used by Alembic.
revision: str = 'f47846f1a638'
down_revision: Union[str, Sequence[str], None] = '965f5718222d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

concert_status_enum = postgresql.ENUM(
    "scheduled", "on_sale", "sold_out", "completed", "cancelled",
    name="concert_status_enum",
    create_type=False,
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
            CREATE TYPE concert_status_enum AS ENUM ('scheduled', 'on_sale', 'sold_out', 'completed', 'cancelled');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    op.create_table(
        "concerts",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("management_companies.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT, not CASCADE: deleting a venue shouldn't silently delete
        # every concert ever held there — that's real historical/ticketing
        # data. A venue with concerts on it can't be deleted at all until
        # those concerts are dealt with first.
        sa.Column(
            "venue_id",
            sa.Integer(),
            sa.ForeignKey("venues.id", onupdate="CASCADE", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.VARCHAR(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # This event's capacity — may be <= venue.total_capacity for a
        # reduced/partial-house event; not DB-enforced (database-design.md
        # §3.7).
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("event_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("doors_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", 
            concert_status_enum,
            nullable=False, 
            server_default="scheduled", 
        ),
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
    op.create_check_constraint("chk_concerts_capacity", "concerts", "capacity > 0")
    op.create_index("ix_concerts_company_id", "concerts", ["company_id"])
    op.create_index("ix_concerts_venue_id", "concerts", ["venue_id"])


def downgrade() -> None:
    op.drop_index("ix_concerts_venue_id", table_name="concerts")
    op.drop_index("ix_concerts_company_id", table_name="concerts")
    op.drop_table("concerts")
    op.execute(sa.text("DROP TYPE IF EXISTS concert_status_enum"))
