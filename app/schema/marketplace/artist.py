import uuid

from pydantic import BaseModel


# A product's resolved artist: an idol or a group. color_hex is set only for idols with a color;
# otherwise the client picks a fallback color.
class ArtistRef(BaseModel):
    type: str  # 'idol' | 'group'
    id: uuid.UUID
    name: str
    color_hex: str | None = None
