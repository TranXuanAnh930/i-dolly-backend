"""create venues table

Revision ID: 965f5718222d
Revises: ccbe2a901666
Create Date: 2026-09-04 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '965f5718222d'
down_revision: Union[str, Sequence[str], None] = 'ccbe2a901666'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "venues",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            index=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.VARCHAR(), nullable=False),
        sa.Column("address", sa.VARCHAR(), nullable=False),
        sa.Column("city", sa.VARCHAR(), nullable=False),
        sa.Column("country", sa.VARCHAR(), nullable=False),
        sa.Column("total_capacity", sa.Integer(), nullable=False),
        sa.Column("contact_info", sa.VARCHAR(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "chk_venues_total_capacity", "venues", "total_capacity > 0"
    )

    # `size` is a GENERATED ALWAYS AS ... STORED column (database-design.md
    # §3.7) — derived from total_capacity, never settable directly, always in
    # sync, no drift possible. Alembic's op.add_column has no first-class
    # support for a generated column, so this one column is raw DDL via
    # op.execute — everything else in this migration uses the normal op.*
    # vocabulary.
    #
    # CORRECTION (originally shipped as `venue_size_enum GENERATED ALWAYS AS
    # (... END::venue_size_enum) STORED` — broke on a real Postgres instance
    # with "generation expression is not immutable"): a GENERATED STORED
    # column requires a strictly IMMUTABLE expression, and Postgres's
    # text->enum cast for a user-defined ENUM type goes through `enum_in()`,
    # which the catalog marks STABLE, not IMMUTABLE — because ALTER TYPE ...
    # ADD VALUE can change an enum's membership at runtime, Postgres can't
    # promise the cast is deterministic forever. This isn't a syntax issue;
    # casting text to a user-defined enum can never appear inside a
    # GENERATED STORED expression, no matter how the CASE is written. Fixed
    # by making `size` a plain VARCHAR instead of `venue_size_enum` — the
    # CASE below still only ever produces one of the four labels, so no
    # separate CHECK constraint is needed to keep that guarantee; a real
    # Postgres enum type was never created for this column, so there's
    # nothing to sa.Enum(...).create()/.drop() in this migration anymore.
    op.execute(sa.text(
        """
        ALTER TABLE venues ADD COLUMN size VARCHAR GENERATED ALWAYS AS (
            CASE
                WHEN total_capacity < 10000 THEN 'small'
                WHEN total_capacity < 20000 THEN 'medium'
                WHEN total_capacity < 50000 THEN 'large'
                ELSE 'stadium'
            END
        ) STORED
        """
    ))


def downgrade() -> None:
    op.drop_table("venues")
