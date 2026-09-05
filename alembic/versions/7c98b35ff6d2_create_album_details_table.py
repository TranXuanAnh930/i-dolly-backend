"""create album_details table

Revision ID: 7c98b35ff6d2
Revises: 67536a8e127a
Create Date: 2026-09-04 15:02:15.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  


# revision identifiers, used by Alembic.
revision: str = '7c98b35ff6d2'
down_revision: Union[str, Sequence[str], None] = '67536a8e127a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

release_format_enum = postgresql.ENUM("physical", "digital", name="release_format_enum", create_type=False)


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
            CREATE TYPE release_format_enum AS ENUM ('physical', 'digital');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    # Covers album, single, AND EP uniformly — no release_type column,
    # products.category_id -> categories.name is the single source of truth
    # for which of the three a row is (database-design.md §3.15/§3.16).
    op.create_table(
        "album_details",
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "idol_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("idols.id", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("groups.id", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("track_count", sa.Integer(), nullable=True),
        sa.Column("format", release_format_enum, nullable=False, server_default="physical"),
        sa.Column("cover_image_url", sa.VARCHAR(), nullable=True),
    )
    op.create_check_constraint("chk_album_details_track_count", "album_details", "track_count > 0")
    # "at least one of" — unlike lightstick_details' strict XOR, an album can
    # credit a solo idol on a group release.
    op.create_check_constraint(
        "chk_album_details_artist", "album_details", "idol_id IS NOT NULL OR group_id IS NOT NULL"
    )
    op.create_index("ix_album_details_idol_id", "album_details", ["idol_id"])
    op.create_index("ix_album_details_group_id", "album_details", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_album_details_group_id", table_name="album_details")
    op.drop_index("ix_album_details_idol_id", table_name="album_details")
    op.drop_table("album_details")
    op.execute(sa.text("DROP TYPE IF EXISTS release_format_enum"))
