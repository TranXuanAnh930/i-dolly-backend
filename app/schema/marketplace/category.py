import uuid

from pydantic import BaseModel, Field


class CategoryBase(BaseModel):
    name:str = Field(..., min_length=1, max_length=100)

class CategoryCreate(CategoryBase):
    id:uuid.UUID

class CategoryUpdate(CategoryBase):
    # Omit to leave the category's resale-cap flag unchanged.
    is_resale_capped: bool | None = None

class CategoryRead(CategoryBase):
    id: uuid.UUID
    is_resale_capped: bool

    model_config = {"from_attributes": True}
