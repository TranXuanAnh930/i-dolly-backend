"""create direct_sale_campaigns table

Revision ID: f8a3c1d9e4b2
Revises: c2d4e8f6a1b3
Create Date: 2026-09-14 00:00:00.000000

Direct-sale ticket types (sale_method='direct') had no on/off sale window at
all — always purchasable once stock allowed it. This gives them the same
"campaign defines when it's actually purchasable" shape lottery tiers
already have via lottery_campaigns, minus the draw step (there's nothing to
draw for a direct sale — the fan just buys it, or doesn't).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f8a3c1d9e4b2'
down_revision: Union[str, Sequence[str], None] = 'c2d4e8f6a1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        DO $$ BEGIN
            CREATE TYPE direct_sale_campaign_status_enum AS ENUM ('open', 'cancelled');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    ))

    op.create_table(
        "direct_sale_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "ticket_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sale_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sale_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("open", "cancelled", name="direct_sale_campaign_status_enum", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "chk_direct_sale_campaigns_window", "direct_sale_campaigns", "sale_end_at > sale_start_at"
    )
    op.create_index("ix_direct_sale_campaigns_ticket_type_id", "direct_sale_campaigns", ["ticket_type_id"])


def downgrade() -> None:
    op.drop_index("ix_direct_sale_campaigns_ticket_type_id", table_name="direct_sale_campaigns")
    op.drop_table("direct_sale_campaigns")
    op.execute(sa.text("DROP TYPE IF EXISTS direct_sale_campaign_status_enum"))
