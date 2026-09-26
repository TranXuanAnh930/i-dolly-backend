import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schema.events import ConcertWithVenue

# Submodule import (not the package) to avoid the talent <-> marketplace schema import cycle.
from app.schema.marketplace.products import ProductCard
from app.schema.talent.idol import IdolWithPositions


class GroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    debut_date: date | None = None
    description: str | None = Field(None, max_length=2000)

class GroupCreate(GroupBase):
    company_id: uuid.UUID

class GroupUpdate(GroupBase):
    pass

class GroupRead(GroupBase):
    id: uuid.UUID
    company_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

# --- page-shaped reads: one bundled response per screen.

class GroupWithCount(GroupRead):
    member_count: int

class GroupsPageRead(BaseModel):
    groups: list[GroupWithCount]

class GroupDetailRead(BaseModel):
    group: GroupRead
    members: list[IdolWithPositions]
    events: list[ConcertWithVenue]
    products: list[ProductCard]

# --- manager/admin settings page (an empty list is a normal result, not a 404).
class ManagerGroupsPageRead(BaseModel):
    groups: list[GroupRead]
