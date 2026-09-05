import uuid
from datetime import datetime
from pydantic import BaseModel

class LotteryEntryApply(BaseModel):
    campaign_id: uuid.UUID

class LotteryEntryRead(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    created_at: datetime
    drawn_at: datetime | None

    model_config = {"from_attributes": True}
