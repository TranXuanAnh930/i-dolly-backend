import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session, selectinload
from app.db.models.payment import Payment
from app.schema.ticket import TicketCreate, TicketUpdate, TicketCheckoutCreate
from app.schema.payment import PaymentStatus
from app.db.models.ticket import Ticket
from app.db.models.ticket_type import TicketType
from app.db.models.concert import Concert
from app.db.models.direct_sale_campaign import DirectSaleCampaign
from app.db.models.lottery_entry import LotteryEntry
from app.db.models.lottery_campaign import LotteryCampaign
from app.db.models.user import Users
from app.exception.checkout import (
    TicketTypeNotFoundError,
    WrongSaleMethodError,
    InsufficientTicketStockError,
    NotOnSaleError,
    PaymentAmountMismatch,
    UnsupportedGatewayError,
    LotteryEntryUnresolvedError,
)
from app.exception.db_triggers import DuplicateIdempotencyKeyError, commit_or_raise, flush_or_raise, FanOnlyPurchaseError, DuplicateConcertTicketError
from app.services.payment_service import create_ticket_payment
from app.services.notification_service import create_notification
from app.utils.tax import with_tax

# ADMIN-ONLY STOPGAP for create/update/delete — see TicketCreate's docstring.
# Fans only ever read their own tickets here. Mirrors
# trg_tickets_one_per_concert (schema.sql) at the service layer.

_LIVE_STATUSES = ("reserved", "pending_payment", "paid", "used")
_UNRESOLVED_LOTTERY_STATUSES = ("pending", "won")

def _existing_live_ticket(db: Session, user_id: uuid.UUID, concert_id: uuid.UUID):
    return (
        db.query(Ticket)
        .join(TicketType, Ticket.ticket_type_id == TicketType.id)
        .filter(
            Ticket.user_id == user_id,
            TicketType.concert_id == concert_id,
            Ticket.status.in_(_LIVE_STATUSES),
        )
        .first()
    )

def _unresolved_lottery_entry(db: Session, user_id: uuid.UUID, concert_id: uuid.UUID):
    # A fan mid-lottery for this concert (still "pending", or "won" but
    # hasn't paid/expired yet — a live ticket from that win is already
    # caught by _existing_live_ticket above, but a *won* entry whose ticket
    # since expired isn't, so this checks the entry itself, not just the
    # ticket) shouldn't also be able to buy a direct-sale ticket for the
    # same concert — only "lost" (or no entry at all) clears this gate.
    return (
        db.query(LotteryEntry)
        .join(LotteryCampaign, LotteryEntry.campaign_id == LotteryCampaign.id)
        .join(TicketType, LotteryCampaign.ticket_type_id == TicketType.id)
        .filter(
            LotteryEntry.user_id == user_id,
            TicketType.concert_id == concert_id,
            LotteryEntry.status.in_(_UNRESOLVED_LOTTERY_STATUSES),
        )
        .first()
    )

# The real direct-sale purchase path — add_ticket below stays the
# admin-only stopgap for the (still unbuilt) lottery draw job. Locks the
# ticket_type row for the whole operation and commits exactly once at the
# end (see create_ticket_payment's docstring) rather than order_service.
# checkout's lock-then-mid-flow-commit pattern, so this can't oversell a
# seat the way that function's own docs admit it can.
def checkout_ticket(db: Session, user_id: uuid.UUID, data: TicketCheckoutCreate) -> Ticket:
    user = db.get(Users, user_id)
    if not user or user.role != "fan":
        # Primary check for trg_tickets_fan_only — the trigger is the
        # backstop (see flush_or_raise below), same split as
        # order_service.checkout's own FanOnlyPurchaseError check.
        raise FanOnlyPurchaseError("Only fan accounts can purchase tickets")
    
    if db.query(Payment).filter(Payment.idempotency_key == data.idempotency_key).first():
        raise DuplicateIdempotencyKeyError() 
    
    ticket_type = db.query(TicketType).filter(TicketType.id == data.ticket_type_id).with_for_update().first()
    if not ticket_type:
        raise TicketTypeNotFoundError("Ticket type not found")
    if ticket_type.sale_method != "direct":
        raise WrongSaleMethodError("This ticket type is not sold directly — apply through the lottery instead")

    now = datetime.now(timezone.utc)
    on_sale = (
        db.query(DirectSaleCampaign)
        .filter(
            DirectSaleCampaign.ticket_type_id == ticket_type.id,
            DirectSaleCampaign.status == "open",
            DirectSaleCampaign.sale_start_at <= now,
            DirectSaleCampaign.sale_end_at >= now,
        )
        .first()
    )
    if not on_sale:
        raise NotOnSaleError("This ticket type is not currently on sale")

    if ticket_type.sold_quantity >= ticket_type.total_quantity:
        raise InsufficientTicketStockError("No tickets left for this tier")

    if _existing_live_ticket(db, user_id, ticket_type.concert_id):
        # Primary check for trg_tickets_one_per_concert — same reasoning as
        # add_ticket's own pre-check below.
        raise DuplicateConcertTicketError("You already hold a live ticket for this concert")

    if _unresolved_lottery_entry(db, user_id, ticket_type.concert_id):
        raise LotteryEntryUnresolvedError(
            "You have a pending or won lottery application for this concert — resolve it before buying a direct-sale ticket"
        )

    total_amount = with_tax(float(ticket_type.price))
    if data.amount != total_amount:
        raise PaymentAmountMismatch("Payment amount does not match ticket price!")

    ticket = Ticket(ticket_type_id=ticket_type.id, user_id=user_id, status="pending_payment")
    db.add(ticket)
    flush_or_raise(db)  # trg_tickets_fan_only / trg_tickets_one_per_concert backstop — also populates ticket.id for create_ticket_payment below

    payment = create_ticket_payment(db, user_id, ticket, data)
    if not payment:
        raise UnsupportedGatewayError("Unsupported payment gateway!")
    if payment.status == PaymentStatus.success:
        if ticket.status == "paid":
            ticket_type.sold_quantity += 1
            create_notification(db, user_id, "ticket_confirmation", ticket_id=ticket.id)

    commit_or_raise(db)  # trg_tickets_fan_only / trg_tickets_one_per_concert / chk_ticket_types_capacity backstop
    db.refresh(ticket)
    return ticket

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

    if _existing_live_ticket(db, data.user_id, ticket_type.concert_id):
        return "conflict"  # trg_tickets_one_per_concert: one live ticket per user per concert

    db_ticket = Ticket(
        ticket_type_id=data.ticket_type_id, user_id=data.user_id, lottery_entry_id=data.lottery_entry_id,
    )
    db.add(db_ticket)
    commit_or_raise(db)  # trg_tickets_fan_only / trg_tickets_one_per_concert backstop
    db.refresh(db_ticket)
    return db_ticket

def get_my_tickets(db: Session, current_user: Users):
    result = (
        db.query(Ticket)
        .filter(Ticket.user_id == current_user.id)
        .options(selectinload(Ticket.ticket_type))
        .all()
    )
    if not result:
        return False
    return result

def get_ticket(db: Session, id: uuid.UUID):
    return (
        db.query(Ticket)
        .filter(Ticket.id == id)
        .options(selectinload(Ticket.ticket_type))
        .first()
    )

# Company-scoped via the concert (Ticket -> TicketType -> Concert.company_id),
# same pattern as concert_service/ticket_type_service. Mirrors
# product_service.get_product_sales_page's shape (page/limit/count/data) for
# the manager-facing "sales history" list/page pair.
def get_concert_ticket_sales(db: Session, concert_id: uuid.UUID, current_user: Users, page: int = 1, limit: int = 10):
    concert = db.get(Concert, concert_id)
    if not concert:
        return "not_found"
    if current_user.role == "manager" and current_user.company_id != concert.company_id:
        return "forbidden"

    query = (
        db.query(Ticket)
        .join(TicketType, Ticket.ticket_type_id == TicketType.id)
        .filter(TicketType.concert_id == concert_id)
        .options(selectinload(Ticket.ticket_type))
        .order_by(Ticket.created_at.desc())
    )
    offset = (page - 1) * limit
    rows = query.offset(offset).limit(limit).all()

    data = [
        {
            "ticket_id": ticket.id,
            "tier": ticket.ticket_type.tier,
            "status": ticket.status,
            "price": ticket.ticket_type.price,
            "source": "lottery" if ticket.lottery_entry_id else "direct",
            "created_at": ticket.created_at,
        }
        for ticket in rows
    ]
    return {"page": page, "limit": limit, "count": len(data), "data": data}

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
