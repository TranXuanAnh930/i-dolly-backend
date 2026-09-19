import uuid
from typing import Literal

from sqlalchemy.orm import Session, joinedload

from app.db.models.events import Concert, LotteryCampaign, LotteryEntry, LotteryPreference, Ticket, TicketType
from app.db.models.identity import Users
from app.exception.db_triggers import commit_or_raise
from app.schema.events import LotteryEntryApply

_LIVE_TICKET_STATUSES = ("reserved", "pending_payment", "paid", "used")

class LotteryEntryService:

    # Fan-facing / self-scoped, same as lottery_preferences: "applying" to a
    # lottery creates an entry owned by current_user. Mirrors the two DB triggers
    # (trg_lottery_entries_cap, trg_lottery_entries_require_preference) at the
    # service layer so a bad apply() returns a clean 400/403 instead of a raw
    # IntegrityError from Postgres.

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == "manager" and current_user.company_id != company_id

    @staticmethod
    def apply_to_lottery(db: Session, data: LotteryEntryApply, current_user: Users) -> LotteryEntry | Literal["fan_only", "not_found", "already_has_ticket", "no_preference", "cap_reached"]:
        if current_user.role != "fan":
            return "fan_only"  # primary check for trg_lottery_entries_fan_only
        campaign = db.get(LotteryCampaign, data.campaign_id)
        if not campaign:
            return "not_found"
        ticket_type = db.get(TicketType, campaign.ticket_type_id)
        if not ticket_type:
            return "not_found"

        # Mirrors ticket_service's own one-ticket-per-concert boundary
        # (trg_tickets_one_per_concert) from the other direction: a fan who
        # already holds a live ticket for this concert — bought directly, or won
        # from an earlier lottery tier — has nothing to gain from also applying
        # here, and letting them in would risk ending up with two tickets for
        # one concert if they later win this tier too.
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
            return "already_has_ticket"

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
            return "no_preference"

        # trg_lottery_entries_cap: existing entries for this (campaign, user) < max_entries_per_user.
        existing_count = (
            db.query(LotteryEntry)
            .filter(LotteryEntry.campaign_id == data.campaign_id, LotteryEntry.user_id == current_user.id)
            .count()
        )
        if existing_count >= campaign.max_entries_per_user:
            return "cap_reached"

        db_entry = LotteryEntry(campaign_id=data.campaign_id, user_id=current_user.id)
        db.add(db_entry)
        commit_or_raise(db)  # backstop for trg_lottery_entries_fan_only/_cap/_require_preference
        db.refresh(db_entry)
        return db_entry

    @staticmethod
    def get_my_entries(db: Session, current_user: Users) -> list[LotteryEntry] | Literal[False]:
        # joinedload both hops — LotteryEntryRead embeds campaign (which embeds
        # ticket_type), and this list can span many different campaigns across
        # a fan's whole history, so lazy-loading each would be its own N+1 at
        # the DB layer (the frontend used to do this same N+1 over HTTP, once
        # per entry — see lotteryEntries.js's old resolveContext).
        result = (
            db.query(LotteryEntry)
            .options(joinedload(LotteryEntry.campaign).joinedload(LotteryCampaign.ticket_type))
            .filter(LotteryEntry.user_id == current_user.id)
            .all()
        )
        if not result:
            return False
        return result

    @staticmethod
    def get_entries_for_campaign(db: Session, campaign_id: uuid.UUID, current_user: Users) -> list[LotteryEntry] | Literal["not_found", "forbidden", False]:
        """Manager/admin view of who has entered a campaign under their own
        company (company_id resolved the same way as lottery_campaign_service:
        campaign -> ticket_type -> concert.company_id)."""
        campaign = db.get(LotteryCampaign, campaign_id)
        if not campaign:
            return "not_found"
        ticket_type = db.get(TicketType, campaign.ticket_type_id)
        concert = db.get(Concert, ticket_type.concert_id) if ticket_type else None
        if not concert:
            return "not_found"
        if LotteryEntryService._manager_scope_violation(current_user, concert.company_id):
            return "forbidden"
        result = db.query(LotteryEntry).filter(LotteryEntry.campaign_id == campaign_id).all()
        if not result:
            return False
        return result
