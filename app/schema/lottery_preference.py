from datetime import datetime
from pydantic import BaseModel, Field

class LotteryPreferenceRead(BaseModel):
    id: int
    concert_id: int
    user_id: int
    ticket_type_id: int
    rank: int
    created_at: datetime

    model_config = {"from_attributes": True}

class LotteryPreferenceSet(BaseModel):
    """Fan submits their full ranked tier preference for one concert, in
    order of preference. Replaces any existing preferences for
    (concert_id, current_user) — see lottery_preference_service.set_preferences.
    rank is derived from list position (1-indexed), not supplied by the fan."""
    concert_id: int
    ticket_type_ids_in_order: list[int] = Field(..., min_length=1)
