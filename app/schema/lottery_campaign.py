import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schema.ticket_type import TicketTypeRead


class LotteryCampaignBase(BaseModel):
    entry_start_at: datetime
    entry_end_at: datetime
    payment_deadline_hours: int = Field(48, gt=0)
    max_entries_per_user: int = Field(1, gt=0)

    @model_validator(mode="after")
    def _check_window(self):
        if self.entry_end_at <= self.entry_start_at:
            raise ValueError("entry_end_at must be after entry_start_at")
        return self

class LotteryCampaignCreate(LotteryCampaignBase):
    ticket_type_id: uuid.UUID

class LotteryCampaignUpdate(LotteryCampaignBase):
    status: str | None = None  # 'open' | 'drawn' | 'completed' | 'cancelled'

class LotteryCampaignRead(LotteryCampaignBase):
    id: uuid.UUID
    ticket_type_id: uuid.UUID
    status: str
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
    # attribute by concert_service.get_concert_detail before this model
    # validates the ORM object (from_attributes reads it via getattr same
    # as any real column).
    entry_count: int = 0

    model_config = {"from_attributes": True}
