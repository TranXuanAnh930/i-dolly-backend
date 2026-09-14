import uuid
from datetime import date

from pydantic import BaseModel, Field, model_validator


class AlbumDetailBase(BaseModel):
    release_date: date | None = None
    track_count: int | None = Field(None, gt=0)
    format: str = "physical"  # 'physical' | 'digital'
    cover_image_url: str | None = None

class AlbumDetailCreate(AlbumDetailBase):
    product_id: uuid.UUID  # must reference an existing products row (created via the products endpoints)
    idol_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_artist(self):
        if self.idol_id is None and self.group_id is None:
            raise ValueError("At least one of idol_id or group_id must be set")
        return self

class AlbumDetailUpdate(AlbumDetailBase):
    # idol_id/group_id deliberately excluded — ownership is set at creation
    # and immutable, same convention as Group/Idol.company_id.
    pass

class AlbumDetailRead(AlbumDetailBase):
    product_id: uuid.UUID
    idol_id: uuid.UUID | None
    group_id: uuid.UUID | None

    model_config = {"from_attributes": True}
