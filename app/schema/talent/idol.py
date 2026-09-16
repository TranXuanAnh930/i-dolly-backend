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

# --- page-shaped reads — one bundled response per screen, assembled
# server-side, instead of the client stitching /idols/all + /idol_colors/all
# + /positions/idol_positions/all together itself.

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
    groups: list[GroupMini]  # for the members-page unit filter only

class IdolDetailGroup(GroupMini):
    description: str | None = None

class IdolDetailRead(BaseModel):
    idol: IdolWithPositions
    group: IdolDetailGroup | None = None
    # Other members of the same group, or other solo idols if this idol has
    # none — whichever the page's "more from this unit" section needs.
    siblings: list[IdolWithPositions] = []

# --- manager/admin settings pages — same one-bundled-response idea, but
# unlike the customer-facing pages above, an empty list here is a normal
# state (a fresh company has no idols yet), not a 404.

class ManagerIdolsPageRead(BaseModel):
    idols: list[IdolRead]
    groups: list[GroupMini]  # for the idol table's "Group" column only

# The group <select> is filtered client-side to the current company
# (myGroups), unlike GroupMini's other uses which only ever display a name
# — so this is the one place group.company_id is needed alongside id/name.
class GroupOptionForCompany(GroupMini):
    company_id: uuid.UUID
    is_active: bool

class ManagerIdolFormPageRead(BaseModel):
    idols: list[IdolRead]  # only read for the isEditing lookup
    groups: list[GroupOptionForCompany]  # the group <select>, filtered by company
    colors: list[IdolColorRead]  # the color <select>
