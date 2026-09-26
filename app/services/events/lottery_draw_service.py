import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, selectinload

from app.cache.invalidation import CacheInvalidation
from app.db.models.events import Concert, LotteryCampaign, LotteryEntry, LotteryPreference, Ticket, TicketType
from app.db.models.identity import Users
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import commit_or_raise
from app.schema.events.lottery_campaign import CampaignStatus
from app.schema.events.lottery_entry import LotteryEntryStatus
from app.schema.events.lottery_result import LotteryResult
from app.schema.events.ticket import TicketStatus
from app.schema.identity import UserRole
from app.schema.shared import NotificationType
from app.services.events.concert_service import ConcertService
from app.services.shared.notification_service import NotificationService


class LotteryDrawService:

    @staticmethod
    def _user_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == UserRole.fan or (current_user.role == UserRole.manager and current_user.company_id != company_id)

    @staticmethod
    def draw_lottery(db: Session, current_user: Users, concert_id: uuid.UUID) -> LotteryResult:
        MAX_RANK = 0
        concert = db.query(Concert).filter(Concert.id == concert_id).first()
        if not concert:
            raise NotFoundError("Concert not found")
        company_id = concert.company_id
        if company_id is None:
            raise NotFoundError("Concert not found")
        if LotteryDrawService._user_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only draw lotteries for their own company's concerts")
        ticket_types = db.query(TicketType).filter(TicketType.concert_id == concert_id).with_for_update().all()
        if not ticket_types:
            raise NotFoundError("Concert has no ticket types")
        ticket_type_ids = [ticket_type.id for ticket_type in ticket_types]
        campaigns = db.query(LotteryCampaign).filter(LotteryCampaign.ticket_type_id.in_(ticket_type_ids), LotteryCampaign.status == CampaignStatus.open).with_for_update().all()
        if not campaigns:
            raise BadRequestError("No open lottery campaigns for this concert")
        for campaign in campaigns:
            if campaign.entry_end_at > datetime.now(timezone.utc):
                raise BadRequestError("Not every lottery campaign for this concert has ended yet")

        preferences = db.query(LotteryPreference).filter(LotteryPreference.concert_id == concert_id, LotteryPreference.ticket_type_id.in_(ticket_type_ids)).all()
        entries = db.query(LotteryEntry).filter(LotteryEntry.campaign_id.in_([campaign.id for campaign in campaigns]), LotteryEntry.status == LotteryEntryStatus.pending).options(selectinload(LotteryEntry.campaign)).with_for_update().all()

        preferences_by_entry = {}
        for entry in entries:
            preference = next(p for p in preferences if (p.user_id == entry.user_id and p.ticket_type_id == entry.campaign.ticket_type_id))
            MAX_RANK = max(MAX_RANK, preference.rank)
            preferences_by_entry[entry.id] = preference.rank

        won_user_ids: set[uuid.UUID] = set()
        lost_user_ids: set[uuid.UUID] = set()

        for rank in range(1, MAX_RANK + 1):
            for campaign in campaigns:
                ticket_type =next(ticket_type for ticket_type in ticket_types if ticket_type.id == campaign.ticket_type_id)
                if ticket_type.total_quantity - ticket_type.sold_quantity > 0:
                    candidates = [
                        entry for entry in entries if entry.campaign_id == campaign.id and entry.status == LotteryEntryStatus.pending and entry.user_id not in won_user_ids and
                        preferences_by_entry[entry.id] == rank
                    ]
                    capacity = min(len(candidates), ticket_type.total_quantity - ticket_type.sold_quantity)
                    winners = secrets.SystemRandom().sample(candidates, capacity)
                    for candidate in winners:
                        candidate.status = LotteryEntryStatus.won
                        candidate.drawn_at = datetime.now(timezone.utc)
                        # Assign the id now: the reminder notification below needs it before flush.
                        new_ticket = Ticket(id=uuid.uuid4(), ticket_type_id=ticket_type.id, user_id=candidate.user_id, status=TicketStatus.pending_payment, lottery_entry_id=candidate.id, payment_deadline_at=datetime.now(timezone.utc)  + timedelta(hours=campaign.payment_deadline_hours))
                        db.add(new_ticket)
                        won_user_ids.add(candidate.user_id)
                        # One lottery_result notification for wins and losses; the client reads
                        # the entry's status to tell them apart.
                        NotificationService.create_notification(db, candidate.user_id, NotificationType.lottery_result, lottery_entry_id=candidate.id)
                        # Sent once at draw time; there's no scheduled reminder closer to the deadline.
                        NotificationService.create_notification(db, candidate.user_id, NotificationType.lottery_payment_reminder, ticket_id=new_ticket.id)
                    ticket_type.sold_quantity += len(winners)

        for entry in entries:
            if entry.status == LotteryEntryStatus.pending:
                entry.status = LotteryEntryStatus.lost
                entry.drawn_at = datetime.now(timezone.utc)
                if entry.user_id not in won_user_ids:
                    lost_user_ids.add(entry.user_id)
                NotificationService.create_notification(db, entry.user_id, NotificationType.lottery_result, lottery_entry_id=entry.id)

        for campaign in campaigns:
            campaign.status = CampaignStatus.drawn
            campaign.draw_at = datetime.now(timezone.utc)

        commit_or_raise(db)
        # The draw changed campaign status, draw_at and sold_quantity in the cached concert detail.
        CacheInvalidation.delete_cached_concert_detail(concert_id)
        # Separate from the "draw triggered" notification sent when the draw was scheduled.
        ConcertService.notify_managers_of_draw_completion(db, concert)

        return LotteryResult(
            concert_id=concert_id,
            won_user_ids=list(won_user_ids),
            lost_user_ids=list(lost_user_ids),
            drawn_at=datetime.now(timezone.utc),
        )
