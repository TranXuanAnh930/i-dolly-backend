"""add is_active to groups and idols

Revision ID: a1f3c9d27e56
Revises: 876977f26275
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3c9d27e56'
down_revision: Union[str, Sequence[str], None] = '876977f26275'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# One concern: soft-delete flag for the talent domain (matches
# users.is_active, e235061d98a8). Fixes a real data-integrity hole —
# group_service.delete_group/idol_service.delete_idol used to db.delete()
# the row outright, which CASCADEs concert_performers (destroying the
# "who performed" record for concerts that already happened) and SET NULLs
# album_details/merch_details (orphaning artist attribution on products
# with real order history). Deactivating in place instead of deleting keeps
# every FK target alive, so that history stays intact.


def upgrade() -> None:
    op.add_column(
        "groups",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "idols",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("idols", "is_active")
    op.drop_column("groups", "is_active")
