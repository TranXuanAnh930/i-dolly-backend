"""add image_url to products

Revision ID: 019b674bf0c1
Revises: 7abe0b6123b3
Create Date: 2026-09-04 16:56:47.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '019b674bf0c1'
down_revision: Union[str, Sequence[str], None] = '7abe0b6123b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: a product can exist with no image yet (matches
    # idols.profile_image_url, added in an earlier migration — same
    # pattern, just closing the gap for products). Holds either a local
    # path (served from /uploads, see main.py + app/utils/storage.py) or a
    # full S3/CDN URL depending on STORAGE_BACKEND — the column doesn't
    # care which, it's just wherever the app's storage backend put the file.
    op.add_column("products", sa.Column("image_url", sa.VARCHAR(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "image_url")
