import uuid
from datetime import datetime
from enum import Enum
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.schema.events.ticket_type import TicketTypeRead


class CampaignStatus(str, Enum):
    open = "open"
    drawn = "drawn"
    completed = "completed"
    cancelled = "cancelled"

class LotteryCampaignBase(BaseModel):
    entry_start_at: datetime
    entry_end_at: datetime
    payment_deadline_hours: int = Field(48, gt=0)
    # max_entries_per_user is deliberately NOT client-settable: pinned to the column's
    # server_default of 1 for now — lottery_draw_service assumes one entry per user per
    # campaign (>1 could draw the same fan twice in one tier, docs/bugs.md #6). Read-only
    # on LotteryCampaignRead below.

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.entry_end_at <= self.entry_start_at:
            raise ValueError("entry_end_at must be after entry_start_at")
        return self

class LotteryCampaignCreate(LotteryCampaignBase):
    ticket_type_id: uuid.UUID

class LotteryCampaignUpdate(LotteryCampaignBase):
    status: CampaignStatus | None = None

class LotteryCampaignRead(LotteryCampaignBase):
    id: uuid.UUID
    ticket_type_id: uuid.UUID
    status: CampaignStatus
    max_entries_per_user: int
    # Written only by the draw job (app/services/lottery_draw_service.py) —
    # never client-supplied. NULL until this campaign is actually drawn.
    draw_at: datetime | None
    created_at: datetime
    # Embedded (via the ORM relationship of the same name) so a caller that
    # already has a campaign doesn't need a second round-trip just to learn
    # its tier/price — see LotteryEntryRead's own comment for where this
    # matters most.
    ticket_type: TicketTypeRead
    # Total fans who've applied — not a mapped column, set as a plain
    # attribute by concert_service.get_concert_detail_public before this model
    # validates the ORM object (from_attributes reads it via getattr same
    # as any real column).
    entry_count: int = 0

    model_config = {"from_attributes": True}
