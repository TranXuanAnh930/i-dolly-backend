from datetime import datetime
from pydantic import BaseModel

class LotteryEntryApply(BaseModel):
    campaign_id: int

class LotteryEntryRead(BaseModel):
    id: int
    campaign_id: int
    user_id: int
    status: str
    created_at: datetime
    drawn_at: datetime | None

    model_config = {"from_attributes": True}
