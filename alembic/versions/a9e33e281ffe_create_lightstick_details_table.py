"""create lightstick_details table

Revision ID: a9e33e281ffe
Revises: 1afe6efdcccb
Create Date: 2026-09-04 15:03:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a9e33e281ffe'
down_revision: Union[str, Sequence[str], None] = '1afe6efdcccb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tied to exactly one idol OR one group (strict XOR) — unlike
    # album_details' "at least one of," a lightstick is one specific design
    # for one specific act, never shared (database-design.md §3.17).
    op.create_table(
        "lightstick_details",
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
        sa.Column("edition", sa.VARCHAR(), nullable=True),
        # Reuses the existing idol_colors lookup rather than a new one — a
        # lightstick's shell/light color is usually the group's or member's
        # signature color.
        sa.Column(
            "color_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("idol_colors.id", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "chk_lightstick_details_owner",
        "lightstick_details",
        "(idol_id IS NOT NULL AND group_id IS NULL) OR (idol_id IS NULL AND group_id IS NOT NULL)",
    )
    op.create_index("ix_lightstick_details_idol_id", "lightstick_details", ["idol_id"])
    op.create_index("ix_lightstick_details_group_id", "lightstick_details", ["group_id"])
    op.create_index("ix_lightstick_details_color_id", "lightstick_details", ["color_id"])


def downgrade() -> None:
    op.drop_index("ix_lightstick_details_color_id", table_name="lightstick_details")
    op.drop_index("ix_lightstick_details_group_id", table_name="lightstick_details")
    op.drop_index("ix_lightstick_details_idol_id", table_name="lightstick_details")
    op.drop_table("lightstick_details")
