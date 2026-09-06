import uuid
from pydantic import BaseModel

# A product's resolved owner — exactly one of idol/group, same
# convention as album_details/merch_details. color_hex is only ever
# set for an idol with a real idol_colors row; a group (which has no color
# of its own) and an idol with none set both leave it null, and the client
# falls back to its own stable palette in that case (see utils/palette.js).
class ArtistRef(BaseModel):
    type: str  # 'idol' | 'group'
    id: uuid.UUID
    name: str
    color_hex: str | None = None
