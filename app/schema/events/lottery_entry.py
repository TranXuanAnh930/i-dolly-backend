import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schema.events.lottery_campaign import LotteryCampaignRead


class LotteryEntryStatus(str, Enum):
    pending = "pending"
    won = "won"
    lost = "lost"
    expired = "expired"

class LotteryEntryApply(BaseModel):
    campaign_id: uuid.UUID

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
