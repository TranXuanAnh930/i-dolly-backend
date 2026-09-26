import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schema.talent.idol_color import IdolColorRead
from app.schema.talent.position import IdolPositionRead


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
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

# --- page-shaped reads: one bundled response per screen.

class GroupMini(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}

class IdolWithPositions(IdolRead):
    idol_positions: list[IdolPositionRead] = []
    color: IdolColorRead | None = None
    group: GroupMini | None = None

class MembersPageRead(BaseModel):
    idols: list[IdolWithPositions]
    groups: list[GroupMini]  # for the members page's group filter

class IdolDetailGroup(GroupMini):
    description: str | None = None

class IdolDetailRead(BaseModel):
    idol: IdolWithPositions
    group: IdolDetailGroup | None = None
    # Other members of the same group, or other solo idols if the idol has no group.
    siblings: list[IdolWithPositions] = []

# --- manager/admin settings pages (an empty list is a normal result, not a 404).

class ManagerIdolsPageRead(BaseModel):
    idols: list[IdolRead]
    groups: list[GroupMini]  # for the idol table's "Group" column

# Group option with company_id, so the form can filter groups to the current company.
class GroupOptionForCompany(GroupMini):
    company_id: uuid.UUID
    is_active: bool

class ManagerIdolFormPageRead(BaseModel):
    idols: list[IdolRead]
    groups: list[GroupOptionForCompany]  # the group <select>, filtered by company
    colors: list[IdolColorRead]  # the color <select>
