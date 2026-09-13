import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from app.schema.venue import VenueRead
from app.schema.ticket_type import TicketTypeRead
from app.schema.lottery_campaign import LotteryCampaignRead
from app.schema.direct_sale_campaign import DirectSaleCampaignRead
from app.schema.lottery_preference import LotteryPreferenceRead

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
    # Every campaign across every tier on this concert — not scoped to "the
    # currently open one" server-side, since which campaign is relevant
    # (open now vs. most recent past one) is a display decision the caller
    # makes, same as before this was embedded here. Bundled in so a concert
    # page never needs a second (or per-tier) request just for campaigns.
    lottery_campaigns: list[LotteryCampaignRead] = []
    direct_sale_campaigns: list[DirectSaleCampaignRead] = []
    # Everything below is personalized for whoever's logged in — all empty/
    # False for a guest, never requires auth to view the rest of this page.
    # Lets the frontend disable the Apply CTA for a fan who's already
    # bought a ticket or won the lottery, and lets LotteryEntryPage.vue
    # pre-fill an existing ranking/entry without its own separate calls.
    has_ticket: bool = False
    has_won_lottery: bool = False
    entered_campaign_ids: list[uuid.UUID] = []
    my_lottery_preferences: list[LotteryPreferenceRead] = []

# --- manager/admin settings page — ManagerEventsPage's table and
# ManagerEventFormPage's venue <select> both need the full venues list
# separately from concerts (a venue not yet booked for any concert must
# still appear in the dropdown), so venues aren't embedded per-concert here
# the way ConcertWithVenue does. An empty list is a normal state, not a 404.
class ManagerEventsPageRead(BaseModel):
    concerts: list[ConcertRead]
    venues: list[VenueRead]
