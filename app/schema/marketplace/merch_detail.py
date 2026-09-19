import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, model_validator


class MerchDetailBase(BaseModel):
    edition: str | None = None
    color_id: uuid.UUID | None = None

class MerchDetailCreate(MerchDetailBase):
    product_id: uuid.UUID  # must reference an existing products row
    idol_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_owner_xor(self) -> Self:
        if (self.idol_id is None) == (self.group_id is None):
            raise ValueError("Exactly one of idol_id or group_id must be set")
        return self

class MerchDetailUpdate(MerchDetailBase):
    # idol_id/group_id deliberately excluded — ownership is immutable after
    # creation, same convention as AlbumDetailUpdate.
    pass

class MerchDetailRead(MerchDetailBase):
    product_id: uuid.UUID
    idol_id: uuid.UUID | None
    group_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
