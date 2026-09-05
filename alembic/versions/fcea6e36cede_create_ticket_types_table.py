"""create ticket_types table

Revision ID: fcea6e36cede
Revises: f6117c2d7b78
Create Date: 2026-09-04 15:00:45.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  


# revision identifiers, used by Alembic.
revision: str = 'fcea6e36cede'
down_revision: Union[str, Sequence[str], None] = 'f6117c2d7b78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ticket_tier_enum = postgresql.ENUM("vip", "premium", "regular", name="ticket_tier_enum", create_type=False)
sale_method_enum = postgresql.ENUM("lottery", "direct", name="sale_method_enum", create_type=False)


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
            CREATE TYPE ticket_tier_enum AS ENUM ('vip', 'premium', 'regular');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))
    op.execute(sa.text(
        """
        DO $$ BEGIN
            CREATE TYPE sale_method_enum AS ENUM ('lottery', 'direct');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    op.create_table(
        "ticket_types",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "concert_id",
            sa.Integer(),
            sa.ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", ticket_tier_enum, nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("sold_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sale_method", sale_method_enum, nullable=False, server_default="lottery"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint("chk_ticket_types_price", "ticket_types", "price >= 0")
    op.create_check_constraint("chk_ticket_types_total_quantity", "ticket_types", "total_quantity >= 0")
    op.create_check_constraint("chk_ticket_types_sold_quantity", "ticket_types", "sold_quantity >= 0")
    # A tier can have TWO rows — one lottery-priced, one direct-priced — since
    # direct-purchase (skip the lottery) tickets sell at a markup
    # (database-design.md §3.10).
    op.create_check_constraint("chk_ticket_types_capacity", "ticket_types", "sold_quantity <= total_quantity")
    op.create_unique_constraint(
        "uq_ticket_types_concert_tier_method", "ticket_types", ["concert_id", "tier", "sale_method"]
    )

    # -------------------------------------------------------------------
    # Hard cap: SUM(ticket_types.total_quantity) for a concert must not
    # exceed concerts.capacity. A plain CHECK can't aggregate across sibling
    # rows, so this is a trigger — schema.sql's own "money/fairness
    # invariant gets a DB backstop" rationale (database-design.md §4.1).
    # -------------------------------------------------------------------
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_enforce_concert_ticket_capacity() RETURNS TRIGGER AS $$
        DECLARE
            concert_capacity INTEGER;
            allocated_total INTEGER;
        BEGIN
            SELECT capacity INTO concert_capacity FROM concerts WHERE id = NEW.concert_id;

            SELECT COALESCE(SUM(total_quantity), 0) INTO allocated_total
            FROM ticket_types
            WHERE concert_id = NEW.concert_id AND id IS DISTINCT FROM NEW.id;

            allocated_total := allocated_total + NEW.total_quantity;

            IF allocated_total > concert_capacity THEN
                RAISE EXCEPTION 'ticket_types.total_quantity across all tiers (%) would exceed concerts.capacity (%) for concert_id=%',
                    allocated_total, concert_capacity, NEW.concert_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_ticket_types_capacity
            BEFORE INSERT OR UPDATE OF total_quantity, concert_id ON ticket_types
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_concert_ticket_capacity();
        """
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ticket_types_capacity ON ticket_types"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_enforce_concert_ticket_capacity()"))
    op.drop_table("ticket_types")
    op.execute(sa.text("DROP TYPE IF EXISTS sale_method_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS ticket_tier_enum"))
