from datetime import datetime
from pydantic import BaseModel, model_validator

class LightstickDetailBase(BaseModel):
    edition: str | None = None
    color_id: int | None = None

class LightstickDetailCreate(LightstickDetailBase):
    product_id: int  # must reference an existing products row
    idol_id: int | None = None
    group_id: int | None = None

    @model_validator(mode="after")
    def _check_owner_xor(self):
        if (self.idol_id is None) == (self.group_id is None):
            raise ValueError("Exactly one of idol_id or group_id must be set")
        return self

class LightstickDetailUpdate(LightstickDetailBase):
    # idol_id/group_id deliberately excluded — ownership is immutable after
    # creation, same convention as AlbumDetailUpdate.
    pass

class LightstickDetailRead(LightstickDetailBase):
    product_id: int
    idol_id: int | None
    group_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
