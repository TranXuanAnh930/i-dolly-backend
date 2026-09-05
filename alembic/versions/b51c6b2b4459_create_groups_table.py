"""create groups table

Revision ID: b51c6b2b4459
Revises: 71b1b0443c96
Create Date: 2026-09-04 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b51c6b2b4459'
down_revision: Union[str, Sequence[str], None] = '71b1b0443c96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey(
                "management_companies.id", onupdate="CASCADE", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("name", sa.VARCHAR(), nullable=False),
        sa.Column("debut_date", sa.Date(), nullable=True),
        sa.Column("description", sa.VARCHAR(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            server_onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    # ON DELETE CASCADE, not SET NULL: company_id is required here (a group
    # always belongs to exactly one company, database-design.md §3.3), so
    # deleting a company deletes its groups too. Contrast with the nullable
    # users.company_id FK (d94268485cfa), which uses SET NULL instead.
    op.create_index("ix_groups_company_id", "groups", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_groups_company_id", table_name="groups")
    op.drop_table("groups")
