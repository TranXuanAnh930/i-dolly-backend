import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from app.schema.venue import VenueRead
from app.schema.ticket_type import TicketTypeRead

class ConcertBase(BaseModel):
    venue_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=300)
    description: str | None = None
    capacity: int = Field(..., gt=0)
    event_datetime: datetime
    doors_open_at: datetime | None = None

class ConcertCreate(ConcertBase):
    company_id: uuid.UUID

class ConcertUpdate(ConcertBase):
    status: str | None = None  # 'scheduled' | 'on_sale' | 'sold_out' | 'completed' | 'cancelled'

class ConcertRead(ConcertBase):
    id: uuid.UUID
    company_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class ConcertPerformerAssign(BaseModel):
    concert_id: uuid.UUID
    idol_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None

class ConcertPerformerRead(BaseModel):
    id: uuid.UUID
    concert_id: uuid.UUID
    idol_id: uuid.UUID | None
    group_id: uuid.UUID | None

    model_config = {"from_attributes": True}

# --- page-shaped reads — one bundled response per screen (see idol.py's
# equivalent comment).

class ConcertWithVenue(ConcertRead):
    venue: VenueRead

class EventsPageRead(BaseModel):
    concerts: list[ConcertWithVenue]

# An idol actually performing at the concert — a group credit expands to
# that group's current members, a solo credit is just that one idol
# (concert_service.get_concert_detail does the expansion/dedup; this is
# only the shape the lineup list needs, not a full IdolRead).
class LineupIdol(BaseModel):
    id: uuid.UUID
    name: str
    profile_image_url: str | None = None
    color_hex: str | None = None

class PerformingGroupMini(BaseModel):
    id: uuid.UUID
    name: str

class ConcertDetailRead(BaseModel):
    concert: ConcertRead
    venue: VenueRead
    ticket_types: list[TicketTypeRead]
    lineup: list[LineupIdol]
    performing_groups: list[PerformingGroupMini]
