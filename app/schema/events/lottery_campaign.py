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
    # max_entries_per_user isn't client-settable; it stays at the DB default of 1 because the draw
    # assumes one entry per user per campaign (docs/bugs.md #6). Read-only on LotteryCampaignRead.

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
    # Set by the lottery draw; None until drawn.
    draw_at: datetime | None
    created_at: datetime
    # Embedded so callers get the tier and price without another request.
    ticket_type: TicketTypeRead
    # Number of applications; set as a plain attribute by concert_service, not a mapped column.
    entry_count: int = 0

    model_config = {"from_attributes": True}
