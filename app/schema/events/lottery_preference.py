import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LotteryPreferenceRead(BaseModel):
    id: uuid.UUID
    concert_id: uuid.UUID
    user_id: uuid.UUID
    ticket_type_id: uuid.UUID
    rank: int
    created_at: datetime

    model_config = {"from_attributes": True}

class LotteryPreferenceSet(BaseModel):
    """A fan's full ranked list of tiers for one concert, replacing any previous ranking.
    Rank is the list position (starting at 1)."""
    concert_id: uuid.UUID
    ticket_type_ids_in_order: list[uuid.UUID] = Field(..., min_length=1)
