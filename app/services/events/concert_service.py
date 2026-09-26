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
from app.exception.db_triggers import commit_or_raise
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
from app.schema.shared import NotificationType
from app.services.shared.notification_service import NotificationService

# A concert in any of these statuses may already have tickets or entries against its
# date/capacity, so it can't be edited until cancelled. Also used by ticket_type_service.
_EVENT_OPEN_STATUSES = {ConcertStatus.on_sale, ConcertStatus.sold_out, ConcertStatus.completed}

class ConcertService:

    # Raises NotFoundError (404), ForbiddenError (403, manager outside their company) or
    # BadRequestError (400, business-rule violation).

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
    def _manager_ids_for_company(db: Session, company_id: uuid.UUID) -> list[uuid.UUID]:
        return [
            row[0]
            for row in db.query(Users.id).filter(Users.role == UserRole.manager, Users.company_id == company_id).all()
        ]

    @staticmethod
    def notify_managers_of_draw_trigger(db: Session, concert: Concert) -> None:
        """Notify every manager at the concert's company that a lottery draw was started.

        The draw runs asynchronously in Celery, so this is the managers' record that it's in flight.
        """
        for manager_id in ConcertService._manager_ids_for_company(db, concert.company_id):
            NotificationService.create_notification(db, manager_id, NotificationType.lottery_draw_triggered, concert_id=concert.id)
        commit_or_raise(db)

    @staticmethod
    def notify_managers_of_draw_failure(db: Session, concert: Concert) -> None:
        """Notify every manager at the concert's company that the lottery draw failed.

        Called from draw_lottery_task after rolling back the failed draw."""
        for manager_id in ConcertService._manager_ids_for_company(db, concert.company_id):
            NotificationService.create_notification(db, manager_id, NotificationType.lottery_draw_failed, concert_id=concert.id)
        commit_or_raise(db)

    @staticmethod
    def notify_managers_of_draw_completion(db: Session, concert: Concert) -> None:
        """Notify every manager at the concert's company that the lottery draw finished.

        Called after the draw has committed, in a separate commit."""
        for manager_id in ConcertService._manager_ids_for_company(db, concert.company_id):
            NotificationService.create_notification(db, manager_id, NotificationType.lottery_draw_completed, concert_id=concert.id)
        commit_or_raise(db)

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
        # Soft delete: tickets and lottery entries cascade off the concert's ticket types, so a
        # hard delete would destroy sales history.
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

    # --- page-shaped reads ---

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

    # Viewer-independent concert detail, cached by CacheService.get_cached_concert_detail.
    # Per-viewer fields stay at their defaults here; get_personalization fills them in uncached.
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
        # Expand group credits to current members, de-duplicating idols credited both solo and
        # via a group.
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

        # Every lottery and direct-sale campaign on this concert, so the event pages need one request.
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

        # Total lottery applications per campaign, attached as a plain attribute for
        # LotteryCampaignRead. Unlike sold_quantity, this isn't capped by total_quantity.
        campaign_ids = [campaign.id for campaign in lottery_campaigns]
        entry_counts = dict(
            db.query(LotteryEntry.campaign_id, func.count(LotteryEntry.id))
            .filter(LotteryEntry.campaign_id.in_(campaign_ids))
            .group_by(LotteryEntry.campaign_id)
            .all()
        ) if campaign_ids else {}
        for campaign in lottery_campaigns:
            campaign.entry_count = entry_counts.get(campaign.id, 0)

        # Per-viewer fields are left at their defaults; see get_personalization.
        return ConcertDetailRead(
            concert=concert,
            venue=concert.venue,
            ticket_types=ticket_types,
            lineup=lineup,
            performing_groups=performing_groups,
            lottery_campaigns=lottery_campaigns,
            direct_sale_campaigns=direct_sale_campaigns,
        )

    # Per-viewer fields for the concert detail page. "Bought" means a paid or used ticket, which
    # covers both direct-sale purchases and paid lottery wins.
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

    # --- manager/admin settings page (an empty list is a normal result, not a 404)

    @staticmethod
    def get_manager_events_page(db: Session) -> ManagerEventsPageRead:
        return ManagerEventsPageRead(concerts=db.query(Concert).all(), venues=db.query(Venue).all())
