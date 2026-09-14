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
    """Fan submits their full ranked tier preference for one concert, in
    order of preference. Replaces any existing preferences for
    (concert_id, current_user) — see lottery_preference_service.set_preferences.
    rank is derived from list position (1-indexed), not supplied by the fan."""
    concert_id: uuid.UUID
    ticket_type_ids_in_order: list[uuid.UUID] = Field(..., min_length=1)
