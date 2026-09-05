"""create concert_performers table

Revision ID: f6117c2d7b78
Revises: f47846f1a638
Create Date: 2026-09-04 15:00:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6117c2d7b78'
down_revision: Union[str, Sequence[str], None] = 'f47846f1a638'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "concert_performers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            index=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "concert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "idol_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("idols.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("groups.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "chk_concert_performers_one_of",
        "concert_performers",
        "(idol_id IS NOT NULL AND group_id IS NULL) OR (idol_id IS NULL AND group_id IS NOT NULL)",
    )
    op.create_index("ix_concert_performers_concert_id", "concert_performers", ["concert_id"])


def downgrade() -> None:
    op.drop_index("ix_concert_performers_concert_id", table_name="concert_performers")
    op.drop_table("concert_performers")
