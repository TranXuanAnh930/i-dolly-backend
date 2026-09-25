import uuid
from datetime import date
from enum import Enum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class ReleaseFormat(str, Enum):
    physical = "physical"
    digital = "digital"

class AlbumDetailBase(BaseModel):
    release_date: date | None = None
    track_count: int | None = Field(None, gt=0)
    format: ReleaseFormat = ReleaseFormat.physical

class AlbumDetailCreate(AlbumDetailBase):
    product_id: uuid.UUID
    idol_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_artist(self) -> Self:
        if self.idol_id is None and self.group_id is None:
            raise ValueError("At least one of idol_id or group_id must be set")
        return self

class AlbumDetailUpdate(AlbumDetailBase):
    # idol_id/group_id can't be changed after creation.
    pass

class AlbumDetailRead(AlbumDetailBase):
    product_id: uuid.UUID
    idol_id: uuid.UUID | None
    group_id: uuid.UUID | None

    model_config = {"from_attributes": True}
