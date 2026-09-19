import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models.events import (
    Concert,
    ConcertPerformer,
    DirectSaleCampaign,
    LotteryCampaign,
    LotteryEntry,
    LotteryPreference,
    Ticket,
    TicketType,
    Venue,
)
from app.db.models.identity import Users
from app.db.models.talent import Group, Idol, ManagementCompany
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.schema.events import (
    ConcertCreate,
    ConcertDetailRead,
    ConcertPerformerAssign,
    ConcertStatus,
    ConcertUpdate,
    EventsPageRead,
    LineupIdol,
    ManagerEventsPageRead,
    PerformingGroupMini,
)
from app.schema.events.lottery_entry import LotteryEntryStatus
from app.schema.events.ticket import TicketStatus
from app.schema.identity import UserRole

# Once a concert has gone on sale (or further), fans may already hold
# tickets or lottery entries against its date/capacity — a manager silently
# moving those out from under them is the thing this blocks. "cancelled" is
# excluded on purpose: cancelling is how a manager unlocks the concert
# again (to reschedule, or resize capacity), same "cancel, don't mutate a
# live event" rule as delete_concert's soft-delete below. Also reused as-is
# by ticket_type_service for the same reason on a ticket type's own
# capacity (total_quantity).
_EVENT_OPEN_STATUSES = {ConcertStatus.on_sale, ConcertStatus.sold_out, ConcertStatus.completed}

class ConcertService:

    # Error convention: NotFoundError (404), ForbiddenError (403, manager
    # acting outside their own company_id), BadRequestError (400, everything
    # else — see individual raise sites for the specific business rule).

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == UserRole.manager and current_user.company_id != company_id

    @staticmethod
    def add_concert(db: Session, concert: ConcertCreate, current_user: Users) -> Concert:
        if ConcertService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage concerts for their own company")
        if not db.get(ManagementCompany, concert.company_id):
            raise NotFoundError("Management company not found")
        if not db.get(Venue, concert.venue_id):
            raise NotFoundError("Venue not found")
        db_concert = Concert(**concert.model_dump())
        db.add(db_concert)
        db.commit()
        db.refresh(db_concert)
        return db_concert

    @staticmethod
    def get_concerts(db: Session) -> list[Concert]:
        return db.query(Concert).all()

    @staticmethod
    def get_concert(db: Session, id: uuid.UUID) -> Concert | None:
        return db.get(Concert, id)

    @staticmethod
    def update_concert(db: Session, id: uuid.UUID, data: ConcertUpdate, current_user: Users) -> Concert:
        db_concert = db.get(Concert, id)
        if not db_concert:
            raise NotFoundError("Concert not found")
        if ConcertService._manager_scope_violation(current_user, db_concert.company_id):
            raise ForbiddenError("Managers can only manage concerts for their own company")
        if (
            current_user.role == UserRole.manager
            and db_concert.status in _EVENT_OPEN_STATUSES
            and (
                data.event_datetime != db_concert.event_datetime
                or data.doors_open_at != db_concert.doors_open_at
                or data.capacity != db_concert.capacity
            )
        ):
            raise ForbiddenError("Concert is already on sale — cancel it first, then edit the date/doors-open time/capacity once it's cancelled")
        if not db.get(Venue, data.venue_id):
            raise NotFoundError("Venue not found")
        db_concert.venue_id = data.venue_id
        db_concert.title = data.title
        db_concert.description = data.description
        db_concert.capacity = data.capacity
        db_concert.event_datetime = data.event_datetime
        db_concert.doors_open_at = data.doors_open_at
        if data.status is not None:
            db_concert.status = data.status
        db.commit()
        db.refresh(db_concert)
        return db_concert

    @staticmethod
    def delete_concert(db: Session, id: uuid.UUID, current_user: Users) -> Concert:
        # Cancel, not db.delete(): ticket_types CASCADEs off concerts.id, and
        # tickets/lottery_entries cascade off ticket_types in turn — hard-
        # deleting a concert with any sales or lottery history would destroy it.
        # Setting status="cancelled" (already a first-class concert_status_enum
        # value the frontend renders everywhere) keeps every FK target alive,
        # same rationale as idol_service.delete_idol's soft delete.
        db_concert = db.get(Concert, id)
        if not db_concert:
            raise NotFoundError("Concert not found")
        if ConcertService._manager_scope_violation(current_user, db_concert.company_id):
            raise ForbiddenError("Managers can only manage concerts for their own company")
        db_concert.status = ConcertStatus.cancelled
        db.commit()
        db.refresh(db_concert)
        return db_concert

    # --- concert_performers ---

    @staticmethod
    def assign_performer(db: Session, data: ConcertPerformerAssign, current_user: Users) -> ConcertPerformer:
        if (data.idol_id is None) == (data.group_id is None):
            raise BadRequestError("Exactly one of idol_id or group_id must be set")  # matching chk_concert_performers_one_of
        concert = db.get(Concert, data.concert_id)
        if not concert:
            raise NotFoundError("Concert not found")
        if ConcertService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage concerts for their own company")
        if data.idol_id is not None and not db.get(Idol, data.idol_id):
            raise NotFoundError("Idol not found")
        if data.group_id is not None and not db.get(Group, data.group_id):
            raise NotFoundError("Group not found")
        db_link = ConcertPerformer(concert_id=data.concert_id, idol_id=data.idol_id, group_id=data.group_id)
        db.add(db_link)
        db.commit()
        db.refresh(db_link)
        return db_link

    @staticmethod
    def get_performers(db: Session, concert_id: uuid.UUID) -> list[ConcertPerformer]:
        return db.query(ConcertPerformer).filter(ConcertPerformer.concert_id == concert_id).all()

    @staticmethod
    def get_all_performers(db: Session) -> list[ConcertPerformer]:
        return db.query(ConcertPerformer).all()

    @staticmethod
    def remove_performer(db: Session, id: uuid.UUID, current_user: Users) -> ConcertPerformer:
        link = db.get(ConcertPerformer, id)
        if not link:
            raise NotFoundError("Performer assignment not found")
        concert = db.get(Concert, link.concert_id)
        if ConcertService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage concerts for their own company")
        db.delete(link)
        db.commit()
        return link

    # --- page-shaped reads (see idol_service.py's equivalent comment) ---

    @staticmethod
    def get_events_page(db: Session) -> EventsPageRead | None:
        concerts = db.query(Concert).options(joinedload(Concert.venue)).all()
        if not concerts:
            return None
        return EventsPageRead(concerts=concerts)

    @staticmethod
    def _lineup_idol(idol: Idol) -> LineupIdol:
        return LineupIdol(
            id=idol.id,
            name=idol.name,
            profile_image_url=idol.profile_image_url,
            color_hex=idol.color.hex_code if idol.color else None,
        )

    # Split from the old single get_concert_detail: everything here is identical for every
    # viewer (including guests), so it's the unit CacheService.get_cached_concert_detail caches
    # verbatim — has_ticket/has_won_lottery/entered_campaign_ids/my_lottery_preferences stay at
    # their False/empty schema defaults here on purpose. get_personalization below computes
    # those per-viewer fields separately, and the router (get_concert_detail_by_id) merges them
    # onto this result uncached, so a cached response never leaks one fan's ticket/lottery
    # state to another.
    @staticmethod
    def get_concert_detail_public(db: Session, id: uuid.UUID) -> ConcertDetailRead | None:
        concert = db.query(Concert).options(joinedload(Concert.venue)).filter(Concert.id == id).first()
        if not concert:
            return None
        ticket_types = db.query(TicketType).filter(TicketType.concert_id == id).all()
        performers = (
            db.query(ConcertPerformer)
            .options(joinedload(ConcertPerformer.idol).selectinload(Idol.color), joinedload(ConcertPerformer.group))
            .filter(ConcertPerformer.concert_id == id)
            .all()
        )
        # A group credit expands to that group's current members, a solo credit
        # is just that one idol — de-duplicated in case the same idol shows up
        # via both a solo and a group credit (mirrors the previous client-side
        # concertsStore.lineupForConcert getter).
        seen_idol_ids = set()
        lineup = []
        seen_group_ids = set()
        performing_groups = []
        for performer in performers:
            if performer.group_id and performer.group:
                if performer.group_id not in seen_group_ids:
                    seen_group_ids.add(performer.group_id)
                    performing_groups.append(PerformingGroupMini(id=performer.group.id, name=performer.group.name))
                members = db.query(Idol).options(selectinload(Idol.color)).filter(Idol.group_id == performer.group_id).all()
                for member in members:
                    if member.id not in seen_idol_ids:
                        seen_idol_ids.add(member.id)
                        lineup.append(ConcertService._lineup_idol(member))
            elif performer.idol_id and performer.idol:
                if performer.idol_id not in seen_idol_ids:
                    seen_idol_ids.add(performer.idol_id)
                    lineup.append(ConcertService._lineup_idol(performer.idol))

        # Every campaign across every tier on this concert, lottery and direct
        # alike — public, not personalized. Bundled here (rather than a
        # separate per-concert campaign endpoint) so EventDetailPage.vue,
        # LotteryEntryPage.vue and TicketPurchasePage.vue each need exactly one
        # request to load, not one call per tier or one call per data source.
        lottery_campaigns = (
            db.query(LotteryCampaign)
            .options(joinedload(LotteryCampaign.ticket_type))
            .join(TicketType, LotteryCampaign.ticket_type_id == TicketType.id)
            .filter(TicketType.concert_id == id)
            .all()
        )
        direct_sale_campaigns = (
            db.query(DirectSaleCampaign)
            .join(TicketType, DirectSaleCampaign.ticket_type_id == TicketType.id)
            .filter(TicketType.concert_id == id)
            .all()
        )

        # How many fans have applied, total — distinct from ticket_type.
        # sold_quantity (only incremented once the draw actually allocates a
        # seat), and not capped by total_quantity the way a direct-sale tier's
        # sold count is. Attached as a plain attribute (not a mapped column) so
        # LotteryCampaignRead's from_attributes pickup just works; a manager's
        # own concert-detail page reads this to show "entries" instead of
        # "sold" for a lottery tier (see ManagerEventFormPage.vue) — public
        # too, same as every other field on this already-public bundle.
        campaign_ids = [campaign.id for campaign in lottery_campaigns]
        entry_counts = dict(
            db.query(LotteryEntry.campaign_id, func.count(LotteryEntry.id))
            .filter(LotteryEntry.campaign_id.in_(campaign_ids))
            .group_by(LotteryEntry.campaign_id)
            .all()
        ) if campaign_ids else {}
        for campaign in lottery_campaigns:
            campaign.entry_count = entry_counts.get(campaign.id, 0)

        # has_ticket/has_won_lottery/entered_campaign_ids/my_lottery_preferences are deliberately
        # left at their ConcertDetailRead defaults (False/[]/[]/[]) — this bundle is public and
        # cacheable precisely because it never depends on who's asking. get_personalization below
        # computes those four fields per request, never cached.
        return ConcertDetailRead(
            concert=concert,
            venue=concert.venue,
            ticket_types=ticket_types,
            lineup=lineup,
            performing_groups=performing_groups,
            lottery_campaigns=lottery_campaigns,
            direct_sale_campaigns=direct_sale_campaigns,
        )

    # The four fields ConcertDetailRead defaults to False/empty for a guest. "Bought" means an
    # actually-paid ticket, not a reserved or abandoned checkout; a lottery ticket has
    # lottery_entry_id set on the Ticket row it creates, so `paid`/`used` here already covers a
    # fan who won and paid, on top of a straight direct-sale purchase. campaign_ids is passed in
    # rather than re-queried — the caller already has it from the (possibly cached)
    # lottery_campaigns list, and re-deriving it here would be a second query for data the
    # public bundle already fetched.
    @staticmethod
    def get_personalization(db: Session, id: uuid.UUID, current_user: Users, campaign_ids: list[uuid.UUID]) -> dict[str, Any]:
        has_ticket = (
            db.query(Ticket)
            .join(TicketType, Ticket.ticket_type_id == TicketType.id)
            .filter(
                TicketType.concert_id == id,
                Ticket.user_id == current_user.id,
                Ticket.status.in_([TicketStatus.paid, TicketStatus.used]),
            )
            .first()
            is not None
        )
        has_won_lottery = (
            db.query(LotteryEntry)
            .join(LotteryCampaign, LotteryEntry.campaign_id == LotteryCampaign.id)
            .join(TicketType, LotteryCampaign.ticket_type_id == TicketType.id)
            .filter(
                TicketType.concert_id == id,
                LotteryEntry.user_id == current_user.id,
                LotteryEntry.status == LotteryEntryStatus.won,
            )
            .first()
            is not None
        )
        entered_campaign_ids = [
            row[0]
            for row in db.query(LotteryEntry.campaign_id)
            .filter(LotteryEntry.user_id == current_user.id, LotteryEntry.campaign_id.in_(campaign_ids))
            .all()
        ] if campaign_ids else []
        my_lottery_preferences = (
            db.query(LotteryPreference)
            .filter(LotteryPreference.concert_id == id, LotteryPreference.user_id == current_user.id)
            .order_by(LotteryPreference.rank)
            .all()
        )
        return {
            "has_ticket": has_ticket,
            "has_won_lottery": has_won_lottery,
            "entered_campaign_ids": entered_campaign_ids,
            "my_lottery_preferences": my_lottery_preferences,
        }

    # --- manager/admin settings page (see idol_service.py's equivalent
    # comment — an empty list here is a normal state, not a 404).

    @staticmethod
    def get_manager_events_page(db: Session) -> ManagerEventsPageRead:
        return ManagerEventsPageRead(concerts=db.query(Concert).all(), venues=db.query(Venue).all())
