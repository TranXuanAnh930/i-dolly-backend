"""create products table

Revision ID: b753e2f6ab31
Revises: 021b68fadc14
Create Date: 2026-01-14 15:14:44.008995

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b753e2f6ab31'
down_revision: Union[str, Sequence[str], None] = 'f2a3135a19da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False)
    )


def downgrade() -> None:
    op.drop_table("products")
