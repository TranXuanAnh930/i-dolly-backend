import uuid
from pydantic import BaseModel, Field

class ManagementCompanyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    contact_email: str | None = Field(None, max_length=200)

class ManagementCompanyCreate(ManagementCompanyBase):
    pass

class ManagementCompanyRead(ManagementCompanyBase):
    id: uuid.UUID

    model_config = {"from_attributes": True}
