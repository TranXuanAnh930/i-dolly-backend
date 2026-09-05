"""add users.company_id foreign key to management_companies

Revision ID: d94268485cfa
Revises: be17057ffa9c
Create Date: 2026-09-04 13:05:02.293571

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd94268485cfa'
down_revision: Union[str, Sequence[str], None] = 'be17057ffa9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Split out from the migration that added the column (d252bd331649) since
    # management_companies didn't exist yet at that point — one concern per
    # migration. SET NULL on delete, not CASCADE: deleting a company shouldn't
    # delete the manager accounts that worked there.
    op.create_foreign_key(
        "fk_users_company",
        "users",
        "management_companies",
        ["company_id"],
        ["id"],
        onupdate="CASCADE",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_company", "users", type_="foreignkey")
