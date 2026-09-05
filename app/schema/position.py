import uuid
from pydantic import BaseModel, Field

class PositionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class PositionCreate(PositionBase):
    pass

class PositionRead(PositionBase):
    id: uuid.UUID

    model_config = {"from_attributes": True}

class IdolPositionAssign(BaseModel):
    idol_id: uuid.UUID
    position_id: uuid.UUID
    is_primary: bool = False

class IdolPositionRead(BaseModel):
    idol_id: uuid.UUID
    position_id: uuid.UUID
    is_primary: bool
    position: PositionRead

    model_config = {"from_attributes": True}
