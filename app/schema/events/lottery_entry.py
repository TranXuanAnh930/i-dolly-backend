import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schema.events.lottery_campaign import LotteryCampaignRead
from app.schema.events.ticket import TicketStatus
from app.schema.events.ticket_type import TicketTier


class LotteryEntryStatus(str, Enum):
    pending = "pending"
    won = "won"
    lost = "lost"
    expired = "expired"

class LotteryEntryApply(BaseModel):
    campaign_id: uuid.UUID

class LotteryEntryApplyBatch(BaseModel):
    """Apply to several of a concert's tiers in one request (all-or-nothing, one rate-limit slot).

    Duplicate campaign_ids are rejected. max_length is a sanity limit, not a business rule.
    """

    campaign_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=10)

    @field_validator("campaign_ids")
    @classmethod
    def _reject_duplicates(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("campaign_ids must not contain duplicates")
        return value

class LotteryEntryRead(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    user_id: uuid.UUID
    status: LotteryEntryStatus
    created_at: datetime
    drawn_at: datetime | None
    # Embeds the campaign and its ticket_type so a fan's entry list needs no extra requests.
    campaign: LotteryCampaignRead

    model_config = {"from_attributes": True}

# Manager view of one decided (won/lost) entry, built by
# LotteryEntryService.get_draw_results_for_concert. Ticket fields are None for lost entries.
class LotteryDrawResultRead(BaseModel):
    lottery_entry_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    ticket_type_id: uuid.UUID
    tier: TicketTier
    status: LotteryEntryStatus
    drawn_at: datetime | None
    ticket_id: uuid.UUID | None
    payment_status: TicketStatus | None
    payment_deadline_at: datetime | None
