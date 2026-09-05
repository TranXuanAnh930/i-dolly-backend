from datetime import datetime
from pydantic import BaseModel, Field

class ConcertBase(BaseModel):
    venue_id: int
    title: str = Field(..., min_length=1, max_length=300)
    description: str | None = None
    capacity: int = Field(..., gt=0)
    event_datetime: datetime
    doors_open_at: datetime | None = None

class ConcertCreate(ConcertBase):
    company_id: int

class ConcertUpdate(ConcertBase):
    status: str | None = None  # 'scheduled' | 'on_sale' | 'sold_out' | 'completed' | 'cancelled'

class ConcertRead(ConcertBase):
    id: int
    company_id: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class ConcertPerformerAssign(BaseModel):
    concert_id: int
    idol_id: int | None = None
    group_id: int | None = None

class ConcertPerformerRead(BaseModel):
    id: int
    concert_id: int
    idol_id: int | None
    group_id: int | None

    model_config = {"from_attributes": True}
