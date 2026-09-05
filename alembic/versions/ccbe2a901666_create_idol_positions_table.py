"""create idol_positions table

Revision ID: ccbe2a901666
Revises: 3bb50b855520
Create Date: 2026-09-04 14:00:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ccbe2a901666'
down_revision: Union[str, Sequence[str], None] = '3bb50b855520'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pure join table — composite PK (idol_id, position_id), no surrogate id
    # column, matching album_genres' shape elsewhere in this design. Both
    # FKs cascade on delete: an idol_positions row has no meaning once
    # either side of it is gone (database-design.md §3.6).
    op.create_table(
        "idol_positions",
        sa.Column(
            "idol_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("idols.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("positions.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("idol_positions")
