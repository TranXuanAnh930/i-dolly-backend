"""extend idol_colors and genres seed data

Revision ID: 10f9dfa05636
Revises: 019b674bf0c1
Create Date: 2026-09-04 18:30:00.000000

Adds more idol_colors and genres rows for the expanded seed roster
(seed.py: 3 companies / 5 groups / 25 idols across a J-Pop, city-pop,
anime-tie-in, gothic, and vocaloid-adjacent lineup) — the original 12
colors and 10 genres weren't enough for a roster this size without
color reuse, and "anime"/"gothic"/"vocaloid"/"j-pop" genres didn't exist
yet. Pure data migration: no schema change, only new rows in two
existing lookup tables — same "extend freely, no downstream migration
needed for a new shade/genre" pattern the original seed rows documented.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10f9dfa05636'
down_revision: Union[str, Sequence[str], None] = '019b674bf0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLORS = [
    {"name": "Sakura Blossom", "hex_code": "#FFC4DD"},
    {"name": "Matcha Green", "hex_code": "#A8C97F"},
    {"name": "Golden Hour", "hex_code": "#FFD966"},
    {"name": "Synth Teal", "hex_code": "#2ED9C3"},
    {"name": "Onyx Black", "hex_code": "#2B2730"},
    {"name": "Blood Rose", "hex_code": "#8B1E3F"},
    {"name": "Moonlight Silver", "hex_code": "#D8D8E0"},
    {"name": "Ghost Lavender", "hex_code": "#B9A6D9"},
    {"name": "Neon Cyan", "hex_code": "#4DE8E0"},
    {"name": "Plum Wine", "hex_code": "#6B2E5F"},
    {"name": "Ivory Frost", "hex_code": "#F5F0E6"},
    {"name": "Steel Grey", "hex_code": "#8A8D91"},
    {"name": "Crimson Ember", "hex_code": "#C4283C"},
    {"name": "Deep Indigo", "hex_code": "#2E2A5E"},
    {"name": "Pastel Aqua", "hex_code": "#B3E5E0"},
    {"name": "Amber Glow", "hex_code": "#FFB84D"},
    {"name": "Twilight Rose", "hex_code": "#B8577E"},
]

NEW_GENRES = ["J-Pop", "Anime", "Vocaloid", "Gothic", "Idol Pop"]


def upgrade() -> None:
    idol_colors = sa.table(
        "idol_colors",
        sa.column("name", sa.VARCHAR()),
        sa.column("hex_code", sa.VARCHAR()),
    )
    op.bulk_insert(idol_colors, NEW_COLORS)

    genres = sa.table(
        "genres",
        sa.column("name", sa.VARCHAR()),
    )
    op.bulk_insert(genres, [{"name": name} for name in NEW_GENRES])


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM idol_colors WHERE name = ANY(:names)"),
        {"names": [c["name"] for c in NEW_COLORS]},
    )
    conn.execute(
        sa.text("DELETE FROM genres WHERE name = ANY(:names)"),
        {"names": NEW_GENRES},
    )
