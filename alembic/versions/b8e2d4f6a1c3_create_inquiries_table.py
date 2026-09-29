"""create inquiries table

Revision ID: b8e2d4f6a1c3
Revises: cf3e0da38a99
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8e2d4f6a1c3'
down_revision: Union[str, Sequence[str], None] = 'cf3e0da38a99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

inquiry_topic_enum = postgresql.ENUM(
    "tickets", "lottery", "orders", "payment", "account", "other",
    name="inquiry_topic_enum",
    create_type=False,
)


# Same idempotent DO $$ ... EXCEPTION WHEN duplicate_object pattern as every
# other enum in this repo (see f15a9003ac94) instead of checkfirst=True.
def upgrade() -> None:
    op.execute(sa.text(
        """
        DO $$ BEGIN
            CREATE TYPE inquiry_topic_enum AS ENUM (
                'tickets',
                'lottery',
                'orders',
                'payment',
                'account',
                'other'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    # user_id is SET NULL on delete: the inquiry is still worth keeping after the account goes.
    op.create_table(
        "inquiries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("topic", inquiry_topic_enum, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_inquiries_user_id", "inquiries", ["user_id"])
    op.create_index("ix_inquiries_email_created_at", "inquiries", ["email", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_inquiries_email_created_at", table_name="inquiries")
    op.drop_index("ix_inquiries_user_id", table_name="inquiries")
    op.drop_table("inquiries")
    op.execute(sa.text("DROP TYPE IF EXISTS inquiry_topic_enum"))
