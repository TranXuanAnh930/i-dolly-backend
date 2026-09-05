"""create album_genres table

Revision ID: 1afe6efdcccb
Revises: 44ccae8cac48
Create Date: 2026-09-04 15:02:45.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1afe6efdcccb'
down_revision: Union[str, Sequence[str], None] = '44ccae8cac48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Shared by every album_details row regardless of category — an "Album"
    # and a "Single" tag genres exactly the same way, keyed off
    # album_details.product_id (database-design.md §3.18).
    op.create_table(
        "album_genres",
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("album_details.product_id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "genre_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("genres.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_album_genres_genre_id", "album_genres", ["genre_id"])


def downgrade() -> None:
    op.drop_index("ix_album_genres_genre_id", table_name="album_genres")
    op.drop_table("album_genres")
