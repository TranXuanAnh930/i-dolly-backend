import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schema.events.concert import ConcertWithVenue
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

# --- page-shaped reads — one bundled response per screen (see idol.py's
# equivalent comment).

class GroupWithCount(GroupRead):
    member_count: int

class GroupsPageRead(BaseModel):
    groups: list[GroupWithCount]

class GroupDetailRead(BaseModel):
    group: GroupRead
    members: list[IdolWithPositions]
    events: list[ConcertWithVenue]
    products: list[ProductCard]

# --- manager/admin settings page — ManagerGroupsPage's table and
# ManagerGroupFormPage's groupById lookup both only need the plain group
# rows, no members/events/products. An empty list is a normal state (a
# fresh company has no groups yet), not a 404.
class ManagerGroupsPageRead(BaseModel):
    groups: list[GroupRead]
