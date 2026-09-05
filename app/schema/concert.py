import uuid
from datetime import datetime
from pydantic import BaseModel, Field

class ConcertBase(BaseModel):
    venue_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=300)
    description: str | None = None
    capacity: int = Field(..., gt=0)
    event_datetime: datetime
    doors_open_at: datetime | None = None

class ConcertCreate(ConcertBase):
    company_id: uuid.UUID

class ConcertUpdate(ConcertBase):
    status: str | None = None  # 'scheduled' | 'on_sale' | 'sold_out' | 'completed' | 'cancelled'

class ConcertRead(ConcertBase):
    id: uuid.UUID
    company_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class ConcertPerformerAssign(BaseModel):
    concert_id: uuid.UUID
    idol_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None

class ConcertPerformerRead(BaseModel):
    id: uuid.UUID
    concert_id: uuid.UUID
    idol_id: uuid.UUID | None
    group_id: uuid.UUID | None

    model_config = {"from_attributes": True}
