"""create idols table

Revision ID: 3bb50b855520
Revises: b51c6b2b4459
Create Date: 2026-09-04 14:00:15.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3bb50b855520'
down_revision: Union[str, Sequence[str], None] = 'b51c6b2b4459'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idols",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey(
                "management_companies.id", onupdate="CASCADE", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        # Nullable: solo idols have no group. ON DELETE SET NULL, not CASCADE
        # — deleting a group shouldn't delete its former members' idol rows,
        # just detach them (database-design.md §3.4).
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("groups.id", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        # Single name field for now — no separate stage name / real name
        # split; real_name is deliberately deferred, not modeled at all
        # right now (database-design.md §3.4/§6).
        sa.Column("name", sa.VARCHAR(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("hometown", sa.VARCHAR(), nullable=True),
        # Nullable: not every idol has a member color assigned yet. Replaces
        # the dropped `talent` field.
        sa.Column(
            "color_id",
            sa.Integer(),
            sa.ForeignKey("idol_colors.id", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("short_intro", sa.VARCHAR(500), nullable=True),
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column("profile_image_url", sa.VARCHAR(), nullable=True),
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
    op.create_index("ix_idols_company_id", "idols", ["company_id"])
    op.create_index("ix_idols_group_id", "idols", ["group_id"])
    op.create_index("ix_idols_color_id", "idols", ["color_id"])

    # App-level invariants (NOT enforced here — matches the existing
    # service-layer validation style, e.g. idol_service on create/update):
    #   * if group_id is set, idols.company_id must equal groups.company_id
    #     for that group.
    #   * two idols in the SAME group probably shouldn't share a color_id
    #     (defeats the point of a member color) — reuse across different
    #     groups/companies is fine. Soft rule, not a DB constraint (see
    #     database-design.md §3.5's reasoning for why this stays a service
    #     check rather than a trigger).


def downgrade() -> None:
    op.drop_index("ix_idols_color_id", table_name="idols")
    op.drop_index("ix_idols_group_id", table_name="idols")
    op.drop_index("ix_idols_company_id", table_name="idols")
    op.drop_table("idols")
