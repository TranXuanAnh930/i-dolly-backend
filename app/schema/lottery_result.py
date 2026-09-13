import uuid
from datetime import datetime
from pydantic import BaseModel

class LotteryResult(BaseModel):
    concert_id: uuid.UUID
    won_user_ids: list[uuid.UUID]
    lost_user_ids: list[uuid.UUID]
    drawn_at: datetime