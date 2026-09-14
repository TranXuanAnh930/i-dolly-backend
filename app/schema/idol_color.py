import uuid

from pydantic import BaseModel, Field


class IdolColorBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    hex_code: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")

class IdolColorCreate(IdolColorBase):
    pass

class IdolColorRead(IdolColorBase):
    id: uuid.UUID

    model_config = {"from_attributes": True}
