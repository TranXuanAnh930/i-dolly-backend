"""drop album_details.cover_image_url

Revision ID: e4f8b2a6c9d1
Revises: 7c7c3f5e19fc
Create Date: 2026-09-24 00:00:00.000000

Every product already carries a single `products.image_url` (`database-design.md` §9's image
pipeline covers it uniformly for albums/merch alike). `album_details.cover_image_url` duplicated
that for album/single/EP products specifically, set independently at creation/update time — the two
could drift (an image re-upload via `POST /products/{id}/image` only ever touched
`products.image_url`, never this column), and the product-card response embedded both
(`ProductCard.image_url` and `ProductCard.album.cover_image_url`) with no guarantee they agreed.
Dropped so every product, album or not, reads its image from exactly one place. One concern: only
this column goes, nothing else about `album_details` changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f8b2a6c9d1'
down_revision: Union[str, Sequence[str], None] = '7c7c3f5e19fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("album_details", "cover_image_url")


def downgrade() -> None:
    op.add_column("album_details", sa.Column("cover_image_url", sa.VARCHAR(), nullable=True))
