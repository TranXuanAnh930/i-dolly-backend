import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schema.events.lottery_campaign import LotteryCampaignRead


class LotteryEntryStatus(str, Enum):
    pending = "pending"
    won = "won"
    lost = "lost"
    expired = "expired"

class LotteryEntryApply(BaseModel):
    campaign_id: uuid.UUID

class LotteryEntryApplyBatch(BaseModel):
    """Apply to several of a concert's tiers in one submission.

    All-or-nothing, and one rate-limit slot for the whole thing — the per-tier
    alternative (a client loop calling /apply once per tier) spends a slot each,
    so a fan ranking more tiers than the limiter allows would get part of their
    submission in and the rest rejected, with no clean way back.

    max_length is a generous ceiling on tiers-per-concert, not a product rule.
    Duplicates are rejected rather than silently deduped: the same campaign
    twice means the caller built the list wrong, and letting it through would
    surface as a confusing "you've already used all your entries" instead.
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
    # Embedded (via the ORM relationship of the same name, itself embedding
    # ticket_type) so a fan's entry list resolves straight down to tier +
    # concert without a per-entry round-trip — see get_my_entries's
    # joinedload. Frontend's lotteryEntries store used to do this resolve
    # itself with 2 extra requests per entry.
    campaign: LotteryCampaignRead

    model_config = {"from_attributes": True}
