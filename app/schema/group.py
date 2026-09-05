from datetime import date, datetime
from pydantic import BaseModel, Field

class GroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    debut_date: date | None = None
    description: str | None = Field(None, max_length=2000)

class GroupCreate(GroupBase):
    company_id: int

class GroupUpdate(GroupBase):
    pass

class GroupRead(GroupBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
