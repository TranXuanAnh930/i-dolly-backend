import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schema.events.direct_sale_campaign import DirectSaleCampaignRead
from app.schema.events.lottery_campaign import LotteryCampaignRead
from app.schema.events.lottery_preference import LotteryPreferenceRead
from app.schema.events.ticket_type import TicketTypeRead
from app.schema.events.venue import VenueRead


class ConcertStatus(str, Enum):
    scheduled = "scheduled"
    on_sale = "on_sale"
    sold_out = "sold_out"
    completed = "completed"
    cancelled = "cancelled"

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
    status: ConcertStatus | None = None

class ConcertRead(ConcertBase):
    id: uuid.UUID
    company_id: uuid.UUID
    status: ConcertStatus
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

# --- page-shaped reads: one bundled response per screen.

class ConcertWithVenue(ConcertRead):
    venue: VenueRead

class EventsPageRead(BaseModel):
    concerts: list[ConcertWithVenue]

# One idol in a concert's lineup (group credits expanded to members by concert_service).
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
    # Every campaign on every tier; the client decides which one to display.
    lottery_campaigns: list[LotteryCampaignRead] = []
    direct_sale_campaigns: list[DirectSaleCampaignRead] = []
    # Per-viewer fields: always False/empty for guests.
    has_ticket: bool = False
    has_won_lottery: bool = False
    entered_campaign_ids: list[uuid.UUID] = []
    my_lottery_preferences: list[LotteryPreferenceRead] = []

# --- manager/admin settings page. Venues are listed separately so unbooked venues still appear
# in the form's dropdown. An empty list is a normal result, not a 404.
class ManagerEventsPageRead(BaseModel):
    concerts: list[ConcertRead]
    venues: list[VenueRead]
