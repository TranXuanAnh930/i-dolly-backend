import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.db.models.events import Concert, LotteryCampaign, LotteryEntry, LotteryPreference, Ticket, TicketType
from app.db.models.identity import Users
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import commit_or_raise, flush_or_raise
from app.schema.events import LotteryDrawResultRead, LotteryEntryApply, LotteryEntryApplyBatch
from app.schema.events.lottery_campaign import CampaignStatus
from app.schema.events.lottery_entry import LotteryEntryStatus
from app.schema.events.ticket import TicketStatus
from app.schema.identity import UserRole
from app.schema.shared import NotificationType
from app.services.shared.notification_service import NotificationService

_LIVE_TICKET_STATUSES = (TicketStatus.reserved, TicketStatus.pending_payment, TicketStatus.paid, TicketStatus.used)

class LotteryEntryService:

    # Fan-facing: entries are owned by current_user. Checks here mirror the DB triggers
    # (trg_lottery_entries_cap, trg_lottery_entries_require_preference) to return clean 400/403s.

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == UserRole.manager and current_user.company_id != company_id

    @staticmethod
    def _stage_entry(db: Session, campaign_id: uuid.UUID, current_user: Users) -> LotteryEntry:
        """Validate and flush one lottery entry without committing.

        Shared by the single and batch apply paths; the caller commits, so a batch is all-or-nothing.
        Flushed rows count toward the cap check for later tiers in the same batch.
        """
        # FOR SHARE: the draw locks campaigns FOR UPDATE, so an apply and a draw can't interleave.
        # An apply that waited on a draw re-reads the row and sees status=drawn below, instead of
        # adding a pending entry the draw never processes. Concurrent applies don't block each other.
        campaign = db.get(LotteryCampaign, campaign_id, with_for_update={"read": True}, populate_existing=True)
        if not campaign:
            raise NotFoundError("Lottery campaign not found")
        now = datetime.now(timezone.utc)
        if campaign.status == CampaignStatus.cancelled:
            raise BadRequestError("This lottery campaign is cancelled")
        if campaign.status != CampaignStatus.open:
            raise BadRequestError("This lottery campaign is no longer accepting entries")
        if now < campaign.entry_start_at:
            raise BadRequestError("Entries for this lottery campaign haven't opened yet")
        if now > campaign.entry_end_at:
            raise BadRequestError("Entries for this lottery campaign have closed")
        ticket_type = db.get(TicketType, campaign.ticket_type_id)
        if not ticket_type:
            raise NotFoundError("Lottery campaign not found")

        # A fan who already holds a live ticket for this concert can't apply.
        existing_ticket = (
            db.query(Ticket)
            .join(TicketType, Ticket.ticket_type_id == TicketType.id)
            .filter(
                Ticket.user_id == current_user.id,
                TicketType.concert_id == ticket_type.concert_id,
                Ticket.status.in_(_LIVE_TICKET_STATUSES),
            )
            .first()
        )
        if existing_ticket:
            raise BadRequestError("You already hold a ticket for this concert")

        # trg_lottery_entries_require_preference: must have ranked this tier.
        has_preference = (
            db.query(LotteryPreference)
            .filter(
                LotteryPreference.concert_id == ticket_type.concert_id,
                LotteryPreference.user_id == current_user.id,
                LotteryPreference.ticket_type_id == ticket_type.id,
            )
            .first()
            is not None
        )
        if not has_preference:
            raise BadRequestError("Rank this ticket tier in your lottery preferences before applying")

        # trg_lottery_entries_cap: existing entries for this (campaign, user) < max_entries_per_user.
        existing_count = (
            db.query(LotteryEntry)
            .filter(LotteryEntry.campaign_id == campaign_id, LotteryEntry.user_id == current_user.id)
            .count()
        )
        if existing_count >= campaign.max_entries_per_user:
            raise BadRequestError("You've already used all your entries for this campaign")

        db_entry = LotteryEntry(campaign_id=campaign_id, user_id=current_user.id)
        db.add(db_entry)
        flush_or_raise(db)  # backstop for trg_lottery_entries_fan_only/_cap/_require_preference
        # Created in the same transaction as the entry.
        NotificationService.create_notification(db, current_user.id, NotificationType.lottery_registered, lottery_entry_id=db_entry.id)
        return db_entry

    @staticmethod
    def apply_to_lottery(db: Session, data: LotteryEntryApply, current_user: Users) -> LotteryEntry:
        if current_user.role != UserRole.fan:
            raise ForbiddenError("Only fan accounts can apply to a lottery")
        db_entry = LotteryEntryService._stage_entry(db, data.campaign_id, current_user)
        commit_or_raise(db)
        db.refresh(db_entry)
        return db_entry

    @staticmethod
    def apply_to_lotteries(db: Session, data: LotteryEntryApplyBatch, current_user: Users) -> list[LotteryEntry]:
        """Apply to several campaigns at once; either every entry is created or none is."""
        if current_user.role != UserRole.fan:
            raise ForbiddenError("Only fan accounts can apply to a lottery")
        entries = [
            LotteryEntryService._stage_entry(db, campaign_id, current_user)
            for campaign_id in data.campaign_ids
        ]
        commit_or_raise(db)
        for entry in entries:
            db.refresh(entry)
        return entries

    @staticmethod
    def get_my_entries(db: Session, current_user: Users) -> list[LotteryEntry]:
        # Eager-load campaign and ticket_type, which LotteryEntryRead embeds, to avoid N+1 queries.
        return (
            db.query(LotteryEntry)
            .options(joinedload(LotteryEntry.campaign).joinedload(LotteryCampaign.ticket_type))
            .filter(LotteryEntry.user_id == current_user.id)
            .all()
        )

    @staticmethod
    def get_entries_for_campaign(db: Session, campaign_id: uuid.UUID, current_user: Users) -> list[LotteryEntry]:
        """Entries for one campaign; managers are limited to their own company's concerts."""
        campaign = db.get(LotteryCampaign, campaign_id)
        if not campaign:
            raise NotFoundError("Lottery campaign not found")
        ticket_type = db.get(TicketType, campaign.ticket_type_id)
        concert = db.get(Concert, ticket_type.concert_id) if ticket_type else None
        if not concert:
            raise NotFoundError("Lottery campaign not found")
        if LotteryEntryService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only view entries for their own company's campaigns")
        return db.query(LotteryEntry).filter(LotteryEntry.campaign_id == campaign_id).all()

    @staticmethod
    def get_draw_results_for_concert(db: Session, concert_id: uuid.UUID, current_user: Users) -> list[LotteryDrawResultRead]:
        """Won and lost entries across every campaign of a concert, with each winner's ticket.

        Managers are limited to their own company's concerts. Undrawn campaigns contribute nothing."""
        concert = db.get(Concert, concert_id)
        if not concert:
            raise NotFoundError("Concert not found")
        if LotteryEntryService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only view lottery results for their own company's concerts")

        entries = (
            db.query(LotteryEntry)
            .join(LotteryCampaign, LotteryEntry.campaign_id == LotteryCampaign.id)
            .join(TicketType, LotteryCampaign.ticket_type_id == TicketType.id)
            .filter(TicketType.concert_id == concert_id, LotteryEntry.status.in_([LotteryEntryStatus.won, LotteryEntryStatus.lost]))
            .options(joinedload(LotteryEntry.user), joinedload(LotteryEntry.campaign).joinedload(LotteryCampaign.ticket_type))
            .all()
        )
        if not entries:
            return []

        # One query for every winner's ticket; lost entries have none.
        tickets_by_entry_id = {
            ticket.lottery_entry_id: ticket
            for ticket in db.query(Ticket).filter(Ticket.lottery_entry_id.in_([entry.id for entry in entries])).all()
        }

        results = []
        for entry in entries:
            ticket = tickets_by_entry_id.get(entry.id)
            results.append(LotteryDrawResultRead(
                lottery_entry_id=entry.id,
                user_id=entry.user_id,
                email=entry.user.email,
                ticket_type_id=entry.campaign.ticket_type_id,
                tier=entry.campaign.ticket_type.tier,
                status=entry.status,
                drawn_at=entry.drawn_at,
                ticket_id=ticket.id if ticket else None,
                payment_status=ticket.status if ticket else None,
                payment_deadline_at=ticket.payment_deadline_at if ticket else None,
            ))
        return results
