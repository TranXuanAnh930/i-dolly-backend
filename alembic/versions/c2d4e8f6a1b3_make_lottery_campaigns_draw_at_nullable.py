"""make lottery_campaigns.draw_at nullable

Revision ID: c2d4e8f6a1b3
Revises: a1f3c9d27e56
Create Date: 2026-09-13 00:00:00.000000

draw_at was modeled as a required, client-supplied "scheduled draw time" —
NOT NULL, checked against entry_end_at, set at campaign creation. That's
backwards: it should record WHEN A CAMPAIGN WAS ACTUALLY DRAWN, written
once by the draw job itself (see app/services/lottery_draw_service.py,
which already does `campaign.draw_at = datetime.now(timezone.utc)` at draw
time — this migration just stops fighting that with a NOT NULL/client-input
requirement). Nullable now; NULL means "not drawn yet."
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c2d4e8f6a1b3'
down_revision: Union[str, Sequence[str], None] = 'a1f3c9d27e56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("lottery_campaigns", "draw_at", nullable=True)
    op.drop_constraint("chk_lottery_campaigns_window", "lottery_campaigns", type_="check")
    op.create_check_constraint(
        "chk_lottery_campaigns_window",
        "lottery_campaigns",
        "entry_end_at > entry_start_at AND (draw_at IS NULL OR draw_at >= entry_end_at)",
    )


def downgrade() -> None:
    # Any existing NULL draw_at rows (any campaign not yet drawn) would
    # violate the restored NOT NULL — this is dev-only, no backfill given.
    op.drop_constraint("chk_lottery_campaigns_window", "lottery_campaigns", type_="check")
    op.create_check_constraint(
        "chk_lottery_campaigns_window",
        "lottery_campaigns",
        "entry_end_at > entry_start_at AND draw_at >= entry_end_at",
    )
    op.alter_column("lottery_campaigns", "draw_at", nullable=False)
