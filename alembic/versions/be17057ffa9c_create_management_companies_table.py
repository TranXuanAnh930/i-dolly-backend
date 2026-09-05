"""create management_companies table

Revision ID: be17057ffa9c
Revises: d252bd331649
Create Date: 2026-09-04 13:04:56.013294

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be17057ffa9c'
down_revision: Union[str, Sequence[str], None] = 'd252bd331649'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "management_companies",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.VARCHAR(), nullable=False),
        sa.Column("description", sa.VARCHAR(), nullable=True),
        sa.Column("contact_email", sa.VARCHAR(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("management_companies")
