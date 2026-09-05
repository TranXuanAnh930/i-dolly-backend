import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field

class IdolBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    group_id: uuid.UUID | None = None
    date_of_birth: date | None = None
    hometown: str | None = Field(None, max_length=200)
    color_id: uuid.UUID | None = None
    short_intro: str | None = Field(None, max_length=500)
    long_description: str | None = None
    profile_image_url: str | None = None

class IdolCreate(IdolBase):
    company_id: uuid.UUID

class IdolUpdate(IdolBase):
    pass

class IdolRead(IdolBase):
    id: uuid.UUID
    company_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
