import uuid
from pydantic import BaseModel, Field

class CategoryBase(BaseModel):
    name:str = Field(..., min_length=1, max_length=100)

class CategoryCreate(CategoryBase):
    id:uuid.UUID

class CategoryUpdate(CategoryBase):
    # Optional: lets an admin flip the data-driven anti-resale flag via the
    # API (database-design.md §4.2 — "an UPDATE, not a migration"). Omitting
    # it leaves the category's existing value untouched.
    is_resale_capped: bool | None = None

class CategoryRead(CategoryBase):
    id: uuid.UUID
    is_resale_capped: bool

    model_config = {"from_attributes": True}
