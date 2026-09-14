import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class VenueBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    address: str = Field(..., min_length=1, max_length=300)
    city: str = Field(..., min_length=1, max_length=100)
    country: str = Field(..., min_length=1, max_length=100)
    total_capacity: int = Field(..., gt=0)
    contact_info: str | None = Field(None, max_length=300)

class VenueCreate(VenueBase):
    pass

class VenueUpdate(VenueBase):
    pass

class VenueRead(VenueBase):
    id: uuid.UUID
    # Derived by Postgres (GENERATED ALWAYS), never client-settable.
    size: str
    created_at: datetime

    model_config = {"from_attributes": True}
