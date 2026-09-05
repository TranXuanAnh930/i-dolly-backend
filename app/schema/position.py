from pydantic import BaseModel, Field

class PositionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class PositionCreate(PositionBase):
    pass

class PositionRead(PositionBase):
    id: int

    model_config = {"from_attributes": True}

class IdolPositionAssign(BaseModel):
    idol_id: int
    position_id: int
    is_primary: bool = False

class IdolPositionRead(BaseModel):
    idol_id: int
    position_id: int
    is_primary: bool
    position: PositionRead

    model_config = {"from_attributes": True}
