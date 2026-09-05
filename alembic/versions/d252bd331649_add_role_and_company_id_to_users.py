"""add role and company_id to users

Revision ID: d252bd331649
Revises: a8b378fe0c4f
Create Date: 2026-09-04 13:04:49.969510

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd252bd331649'
down_revision: Union[str, Sequence[str], None] = 'a8b378fe0c4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Defined at module scope (not inline in the column) so upgrade() and
# downgrade() can both reference the same type object without recreating it —
# create_type=False is passed to add_column below since we create/drop the
# Postgres ENUM type explicitly, ourselves, rather than relying on
# op.add_column to do it implicitly.
user_role_enum = sa.Enum("admin", "manager", "fan", name="user_role_enum")


def upgrade() -> None:
    bind = op.get_bind()
    user_role_enum.create(bind, checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "role",
            user_role_enum,
            nullable=False,
            server_default="fan",
        ),
    )
    # No FK yet — management_companies doesn't exist until the next migration.
    # Added here nullable; the FK constraint itself lands in a later, separate
    # migration once management_companies exists (one concern per migration).
    op.add_column(
        "users",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Indexed now (same convention as every other *_company_id FK column in
    # this design — groups, idols, concerts) since manager-scoped queries
    # will filter on it once the FK/table exist.
    op.create_index("ix_users_company_id", "users", ["company_id"])

    # Backfill: every existing is_admin=true row becomes role='admin'.
    # Everyone else already got 'fan' from the column's server_default above.
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = true")

    # NOTE: is_admin itself is deliberately NOT dropped here — CLAUDE.md/
    # database-design.md both call for a later, separate migration once no
    # application code reads is_admin anymore. Don't fold that into this one.


def downgrade() -> None:
    op.drop_index("ix_users_company_id", table_name="users")
    op.drop_column("users", "company_id")
    op.drop_column("users", "role")
    user_role_enum.drop(op.get_bind(), checkfirst=True)
