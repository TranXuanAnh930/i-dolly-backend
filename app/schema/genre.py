import uuid

from pydantic import BaseModel, Field


class GenreBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class GenreCreate(GenreBase):
    pass

class GenreRead(GenreBase):
    id: uuid.UUID

    model_config = {"from_attributes": True}

class AlbumGenreAssign(BaseModel):
    product_id: uuid.UUID
    genre_id: uuid.UUID

class AlbumGenreRead(BaseModel):
    product_id: uuid.UUID
    genre_id: uuid.UUID

    model_config = {"from_attributes": True}
