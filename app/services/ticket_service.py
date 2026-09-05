import uuid
from sqlalchemy.orm import Session
from app.schema.ticket import TicketCreate, TicketUpdate
from app.db.models.ticket import Ticket
from app.db.models.ticket_type import TicketType
from app.db.models.lottery_entry import LotteryEntry
from app.db.models.user import Users
from app.exception.db_triggers import commit_or_raise

# ADMIN-ONLY STOPGAP for create/update/delete — see TicketCreate's docstring.
# Fans only ever read their own tickets here. Mirrors
# trg_tickets_one_per_concert (schema.sql) at the service layer.

_LIVE_STATUSES = ("reserved", "pending_payment", "paid", "used")

def add_ticket(db: Session, data: TicketCreate):
    ticket_type = db.get(TicketType, data.ticket_type_id)
    if not ticket_type:
        return "not_found"
    target_user = db.get(Users, data.user_id)
    if not target_user:
        return "not_found"
    if target_user.role != "fan":
        # Primary check for trg_tickets_fan_only — checks the ticket's
        # intended owner (data.user_id), not the caller, since this
        # endpoint is admin-only (an admin issuing a ticket to a fan).
        return "fan_only"
    if data.lottery_entry_id is not None and not db.get(LotteryEntry, data.lottery_entry_id):
        return "not_found"

    existing_live = (
        db.query(Ticket)
        .join(TicketType, Ticket.ticket_type_id == TicketType.id)
        .filter(
            Ticket.user_id == data.user_id,
            TicketType.concert_id == ticket_type.concert_id,
            Ticket.status.in_(_LIVE_STATUSES),
        )
        .first()
    )
    if existing_live:
        return "conflict"  # trg_tickets_one_per_concert: one live ticket per user per concert

    db_ticket = Ticket(
        ticket_type_id=data.ticket_type_id, user_id=data.user_id, lottery_entry_id=data.lottery_entry_id,
    )
    db.add(db_ticket)
    commit_or_raise(db)  # trg_tickets_fan_only / trg_tickets_one_per_concert backstop
    db.refresh(db_ticket)
    return db_ticket

def get_my_tickets(db: Session, current_user: Users):
    result = db.query(Ticket).filter(Ticket.user_id == current_user.id).all()
    if not result:
        return False
    return result

def get_ticket(db: Session, id: uuid.UUID):
    return db.get(Ticket, id)

def update_ticket(db: Session, id: uuid.UUID, data: TicketUpdate):
    db_ticket = db.get(Ticket, id)
    if not db_ticket:
        return "not_found"
    if data.status is not None:
        db_ticket.status = data.status
    if data.issued_code is not None:
        db_ticket.issued_code = data.issued_code
    if data.payment_id is not None:
        db_ticket.payment_id = data.payment_id
    if data.payment_deadline_at is not None:
        db_ticket.payment_deadline_at = data.payment_deadline_at
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

def delete_ticket(db: Session, id: uuid.UUID):
    db_ticket = db.get(Ticket, id)
    if not db_ticket:
        return "not_found"
    db.delete(db_ticket)
    db.commit()
    return True
