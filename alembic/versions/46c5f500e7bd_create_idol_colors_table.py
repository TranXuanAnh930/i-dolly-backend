"""create idol_colors table

Revision ID: 46c5f500e7bd
Revises: d94268485cfa
Create Date: 2026-09-04 13:05:14.081569

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '46c5f500e7bd'
down_revision: Union[str, Sequence[str], None] = 'd94268485cfa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Seed data — cute pastel/bright "member color" palette. A lookup table, not
# an enum: extend freely later, no migration needed for a new shade.
SEED_COLORS = [
    {"name": "Cotton Candy Pink", "hex_code": "#FFB3D9"},
    {"name": "Butter Yellow", "hex_code": "#FFF3B0"},
    {"name": "Sky Mint", "hex_code": "#A0E7E5"},
    {"name": "Lavender Dream", "hex_code": "#C9A9E8"},
    {"name": "Peach Sorbet", "hex_code": "#FFD3B0"},
    {"name": "Baby Blue", "hex_code": "#AEE1FF"},
    {"name": "Lilac Bloom", "hex_code": "#D9B8FF"},
    {"name": "Mint Cream", "hex_code": "#B5EAD7"},
    {"name": "Coral Blush", "hex_code": "#FFB7B2"},
    {"name": "Periwinkle Pop", "hex_code": "#C7CEEA"},
    {"name": "Bubblegum Purple", "hex_code": "#E4C1F9"},
    {"name": "Tangerine Pop", "hex_code": "#FFB570"},
]


def upgrade() -> None:
    op.create_table(
        "idol_colors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.VARCHAR(), nullable=False, unique=True),
        sa.Column("hex_code", sa.VARCHAR(7), nullable=False, unique=True),
    )
    op.create_check_constraint(
        "chk_idol_colors_hex_format",
        "idol_colors",
        "hex_code ~ '^#[0-9A-Fa-f]{6}$'",
    )

    idol_colors = sa.table(
        "idol_colors",
        sa.column("name", sa.VARCHAR()),
        sa.column("hex_code", sa.VARCHAR()),
    )
    op.bulk_insert(idol_colors, SEED_COLORS)


def downgrade() -> None:
    op.drop_table("idol_colors")
