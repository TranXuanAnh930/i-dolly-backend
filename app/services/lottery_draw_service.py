import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, selectinload

from app.db.models.concert import Concert
from app.db.models.lottery_campaign import LotteryCampaign
from app.db.models.lottery_entry import LotteryEntry
from app.db.models.lottery_preference import LotteryPreference
from app.db.models.ticket import Ticket
from app.db.models.ticket_type import TicketType
from app.db.models.user import Users
from app.exception.db_triggers import commit_or_raise
from app.services.notification_service import create_notification


def _user_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "fan" or (current_user.role == "manager" and current_user.company_id != company_id)

def draw_lottery(db: Session, current_user: Users, concert_id: uuid.UUID) -> dict:
    MAX_RANK = 0
    concert = db.query(Concert).filter(Concert.id == concert_id).first()
    if not concert:
        return "not_found"
    company_id = concert.company_id
    if company_id is None:
        return "not_found"
    if _user_scope_violation(current_user, company_id):
        return "forbidden"
    ticket_types = db.query(TicketType).filter(TicketType.concert_id == concert_id).with_for_update().all()
    if not ticket_types:
        return "not_found"    
    ticket_type_ids = [ticket_type.id for ticket_type in ticket_types]
    campaigns = db.query(LotteryCampaign).filter(LotteryCampaign.ticket_type_id.in_(ticket_type_ids), LotteryCampaign.status == "open").with_for_update().all()
    if not campaigns:
        return "no_open_campaigns"
    for campaign in campaigns:
        if campaign.entry_end_at > datetime.now(timezone.utc):
            return "campaign_not_ended"

    preferences = db.query(LotteryPreference).filter(LotteryPreference.concert_id == concert_id, LotteryPreference.ticket_type_id.in_(ticket_type_ids)).all()
    entries = db.query(LotteryEntry).filter(LotteryEntry.campaign_id.in_([campaign.id for campaign in campaigns]), LotteryEntry.status == "pending").options(selectinload(LotteryEntry.campaign)).with_for_update().all()
    
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
                    entry for entry in entries if entry.campaign_id == campaign.id and entry.status == "pending" and entry.user_id not in won_user_ids and 
                    preferences_by_entry[entry.id] == rank
                ]
                capacity = min(len(candidates), ticket_type.total_quantity - ticket_type.sold_quantity)
                winners = secrets.SystemRandom().sample(candidates, capacity)
                for candidate in winners:
                    candidate.status = "won"
                    new_ticket = Ticket(ticket_type_id=ticket_type.id, user_id=candidate.user_id, status="pending_payment", lottery_entry_id=candidate.id, payment_deadline_at=datetime.now(timezone.utc)  + timedelta(hours=campaign.payment_deadline_hours))
                    db.add(new_ticket)
                    won_user_ids.add(candidate.user_id)
                    # Same row for win or loss — a lottery_result notification
                    # always carries lottery_entry_id, and the client tells
                    # the two apart by reading entries.status off the FK'd
                    # row, same as everywhere else "which of the four FKs is
                    # set" already drives the meaning (database-design.md
                    # §3.19), rather than a second notification type.
                    create_notification(db, candidate.user_id, "lottery_result", lottery_entry_id=candidate.id)
                    # Fired once, here, at draw time — not a scheduled
                    # nag closer to the deadline (that would need a cron/
                    # Celery Beat job, deliberately out of scope for this
                    # phase, see project_status.md §5). new_ticket.id is
                    # already populated (Ticket.id defaults client-side via
                    # uuid.uuid4, no flush needed) by the time this runs.
                    create_notification(db, candidate.user_id, "lottery_payment_reminder", ticket_id=new_ticket.id)
                ticket_type.sold_quantity += len(winners)

    for entry in entries:
        if entry.status == "pending":
            entry.status = "lost"
            if entry.user_id not in won_user_ids:
                lost_user_ids.add(entry.user_id)
            create_notification(db, entry.user_id, "lottery_result", lottery_entry_id=entry.id)

    for campaign in campaigns:
        campaign.status = "drawn"
        campaign.draw_at = datetime.now(timezone.utc)

    commit_or_raise(db)

    return {
        "concert_id": concert_id,
        "won_user_ids": list(won_user_ids),
        "lost_user_ids": list(lost_user_ids),
        "drawn_at": datetime.now(timezone.utc)
    }
