import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field
from app.schema.idol_color import IdolColorRead
from app.schema.position import IdolPositionRead

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
