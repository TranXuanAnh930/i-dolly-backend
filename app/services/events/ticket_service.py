import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session, selectinload

from app.cache.invalidation import CacheInvalidation
from app.celery_app import celery_app
from app.db.models.events import Concert, DirectSaleCampaign, LotteryCampaign, LotteryEntry, Ticket, TicketType
from app.db.models.identity import Users
from app.db.models.marketplace import Payment
from app.exception.checkout import (
    InsufficientTicketStockError,
    LotteryEntryUnresolvedError,
    NotOnSaleError,
    PaymentAmountMismatch,
    TicketNotFoundError,
    TicketNotPayableError,
    TicketTypeNotFoundError,
    UnsupportedGatewayError,
    WrongSaleMethodError,
)
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import (
    DuplicateConcertTicketError,
    DuplicateIdempotencyKeyError,
    FanOnlyPurchaseError,
    commit_or_raise,
    flush_or_raise,
)
from app.schema.events import (
    TicketCheckoutCreate,
    TicketCreate,
    TicketSaleRead,
    TicketSalesPageRead,
    TicketUpdate,
    WonTicketCheckoutCreate,
)
from app.schema.events.direct_sale_campaign import DirectSaleCampaignStatus
from app.schema.events.lottery_entry import LotteryEntryStatus
from app.schema.events.ticket import TicketStatus
from app.schema.events.ticket_type import SaleMethod
from app.schema.identity import UserRole
from app.schema.marketplace import PaymentStatus
from app.schema.shared import NotificationType
from app.services.marketplace.payment_service import PaymentService
from app.services.shared.notification_service import NotificationService
from app.utils.email_templates import EmailTemplate
from app.utils.tax import with_tax

# Fans read their own tickets and buy via checkout; create/update/delete are admin-only.
# Service-level checks mirror trg_tickets_one_per_concert.

_LIVE_STATUSES = (TicketStatus.reserved, TicketStatus.pending_payment, TicketStatus.paid, TicketStatus.used)
_UNRESOLVED_LOTTERY_STATUSES = (LotteryEntryStatus.pending, LotteryEntryStatus.won)

class TicketService:

    @staticmethod
    def _existing_live_ticket(db: Session, user_id: uuid.UUID, concert_id: uuid.UUID) -> Ticket | None:
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

    @staticmethod
    def _unresolved_lottery_entry(db: Session, user_id: uuid.UUID, concert_id: uuid.UUID) -> LotteryEntry | None:
        # A pending or won (but unresolved) lottery entry for this concert blocks a direct-sale
        # purchase; only a lost entry or no entry allows it.
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

    # Direct-sale purchase. Holds a row lock on the ticket type until the single commit at the end,
    # so two fans can't both buy the last seat.
    @staticmethod
    def checkout_ticket(db: Session, user_id: uuid.UUID, data: TicketCheckoutCreate) -> Ticket:
        user = db.query(Users).filter(Users.id == user_id).with_for_update().first()
        if not user or user.role != UserRole.fan:
            # Primary check; trg_tickets_fan_only is the backstop.
            raise FanOnlyPurchaseError("Only fan accounts can purchase tickets")

        if db.query(Payment).filter(Payment.idempotency_key == data.idempotency_key).first():
            raise DuplicateIdempotencyKeyError() 

        ticket_type = db.query(TicketType).filter(TicketType.id == data.ticket_type_id).with_for_update().first()
        if not ticket_type:
            raise TicketTypeNotFoundError("Ticket type not found")
        if ticket_type.sale_method != SaleMethod.direct:
            raise WrongSaleMethodError("This ticket type is not sold directly — apply through the lottery instead")

        now = datetime.now(timezone.utc)
        on_sale = (
            db.query(DirectSaleCampaign)
            .filter(
                DirectSaleCampaign.ticket_type_id == ticket_type.id,
                DirectSaleCampaign.status == DirectSaleCampaignStatus.open,
                DirectSaleCampaign.sale_start_at <= now,
                DirectSaleCampaign.sale_end_at >= now,
            )
            .first()
        )
        if not on_sale:
            raise NotOnSaleError("This ticket type is not currently on sale")

        if ticket_type.sold_quantity >= ticket_type.total_quantity:
            raise InsufficientTicketStockError("No tickets left for this tier")

        if TicketService._existing_live_ticket(db, user_id, ticket_type.concert_id):
            # Primary check; trg_tickets_one_per_concert is the backstop.
            raise DuplicateConcertTicketError("You already hold a live ticket for this concert")

        if TicketService._unresolved_lottery_entry(db, user_id, ticket_type.concert_id):
            raise LotteryEntryUnresolvedError(
                "You have a pending or won lottery application for this concert — resolve it before buying a direct-sale ticket"
            )

        total_amount = with_tax(float(ticket_type.price))
        if data.amount != total_amount:
            raise PaymentAmountMismatch("Payment amount does not match ticket price!")

        ticket = Ticket(ticket_type_id=ticket_type.id, user_id=user_id, status=TicketStatus.pending_payment)
        db.add(ticket)
        flush_or_raise(db)  # populates ticket.id for create_ticket_payment

        payment = PaymentService.create_ticket_payment(db, user_id, ticket, data)
        if not payment:
            raise UnsupportedGatewayError("Unsupported payment gateway!")
        confirmed = payment.status == PaymentStatus.success and ticket.status == TicketStatus.paid
        if confirmed:
            ticket_type.sold_quantity += 1
            NotificationService.create_notification(db, user_id, NotificationType.ticket_confirmation, ticket_id=ticket.id)
        commit_or_raise(db)
        # sold_quantity is part of the cached concert detail.
        CacheInvalidation.delete_cached_concert_detail(ticket_type.concert_id)
        # Only after the commit succeeded, so a failed commit never sends a confirmation.
        if confirmed:
            email_body = EmailTemplate.TICKET_CONFIRMED.render(
                email=user.email, ticket_id=ticket.id, tier=ticket_type.tier, price=ticket_type.price
            )
            celery_app.send_task("app.tasks.email.send_email", args=[user.email, EmailTemplate.TICKET_CONFIRMED.subject, email_body])
        db.refresh(ticket)
        return ticket

    # Pays for a ticket created by the lottery draw. The draw already counted the seat in
    # sold_quantity, so this doesn't change it.
    @staticmethod
    def checkout_won_ticket(db: Session, user_id: uuid.UUID, ticket_id: uuid.UUID, data: WonTicketCheckoutCreate) -> Ticket:
        if db.query(Payment).filter(Payment.idempotency_key == data.idempotency_key).first():
            raise DuplicateIdempotencyKeyError()

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).with_for_update().first()
        if not ticket or ticket.user_id != user_id:
            raise TicketNotFoundError("Ticket not found")

        ticket_type = db.query(TicketType).filter(TicketType.id == ticket.ticket_type_id).with_for_update().first()
        if not ticket_type:
            raise TicketNotPayableError("This ticket isn't a payable lottery win")

        if ticket_type.sale_method == SaleMethod.direct or ticket.status != TicketStatus.pending_payment:
            raise TicketNotPayableError("This ticket isn't a payable lottery win")

        if ticket.payment_deadline_at and ticket.payment_deadline_at < datetime.now(timezone.utc):
            # Past the deadline: expire the ticket and release its seat.
            ticket.status = TicketStatus.expired
            ticket_type.sold_quantity -= 1
            commit_or_raise(db)
            CacheInvalidation.delete_cached_concert_detail(ticket_type.concert_id)
            raise TicketNotPayableError("The payment deadline for this ticket has passed")

        total_amount = with_tax(float(ticket_type.price))
        if data.amount != total_amount:
            raise PaymentAmountMismatch("Payment amount does not match ticket price!")

        payment = PaymentService.create_ticket_payment(db, user_id, ticket, data)
        if not payment:
            raise UnsupportedGatewayError("Unsupported payment gateway!")
        confirmed = payment.status == PaymentStatus.success
        if confirmed:
            NotificationService.create_notification(db, user_id, NotificationType.lottery_payment_confirmation, ticket_id=ticket.id)

        commit_or_raise(db)
        # Only after the commit succeeded, so a failed commit never sends a confirmation.
        user = db.get(Users, user_id) if confirmed else None
        if user:
            email_body = EmailTemplate.LOTTERY_PAYMENT_CONFIRMED.render(
                email=user.email, ticket_id=ticket.id, tier=ticket_type.tier, price=ticket_type.price
            )
            celery_app.send_task(
                "app.tasks.email.send_email", args=[user.email, EmailTemplate.LOTTERY_PAYMENT_CONFIRMED.subject, email_body]
            )
        db.refresh(ticket)
        return ticket

    @staticmethod
    def add_ticket(db: Session, data: TicketCreate) -> Ticket:
        ticket_type = db.get(TicketType, data.ticket_type_id)
        if not ticket_type:
            raise NotFoundError("Ticket type not found")
        target_user = db.get(Users, data.user_id)
        if not target_user:
            raise NotFoundError("User not found")
        if target_user.role != UserRole.fan:
            # Checks the ticket's recipient (data.user_id), not the admin caller.
            raise ForbiddenError("Tickets can only be issued to fan accounts")
        if data.lottery_entry_id is not None and not db.get(LotteryEntry, data.lottery_entry_id):
            raise NotFoundError("Lottery entry not found")

        if TicketService._existing_live_ticket(db, data.user_id, ticket_type.concert_id):
            raise BadRequestError("This user already holds a live ticket for this concert")

        db_ticket = Ticket(
            ticket_type_id=data.ticket_type_id, user_id=data.user_id, lottery_entry_id=data.lottery_entry_id,
        )
        db.add(db_ticket)
        commit_or_raise(db)
        db.refresh(db_ticket)
        return db_ticket

    @staticmethod
    def get_my_tickets(db: Session, current_user: Users) -> list[Ticket]:
        return (
            db.query(Ticket)
            .filter(Ticket.user_id == current_user.id)
            .options(selectinload(Ticket.ticket_type))
            .all()
        )

    @staticmethod
    def get_ticket(db: Session, id: uuid.UUID) -> Ticket | None:
        return (
            db.query(Ticket)
            .filter(Ticket.id == id)
            .options(selectinload(Ticket.ticket_type))
            .first()
        )

    # Paginated ticket sales for one concert; managers are limited to their own company.
    @staticmethod
    def get_concert_ticket_sales(db: Session, concert_id: uuid.UUID, current_user: Users, page: int = 1, limit: int = 10) -> TicketSalesPageRead:
        concert = db.get(Concert, concert_id)
        if not concert:
            raise NotFoundError("Concert not found")
        if current_user.role == UserRole.manager and current_user.company_id != concert.company_id:
            raise ForbiddenError("Managers can only view ticket sales for their own company's concerts")

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
            TicketSaleRead(
                ticket_id=ticket.id,
                tier=ticket.ticket_type.tier,
                status=ticket.status,
                price=ticket.ticket_type.price,
                source=SaleMethod.lottery if ticket.ticket_type.sale_method == SaleMethod.lottery else SaleMethod.direct,
                created_at=ticket.created_at,
            )
            for ticket in rows
        ]
        return TicketSalesPageRead(page=page, limit=limit, count=len(data), data=data)

    @staticmethod
    def update_ticket(db: Session, id: uuid.UUID, data: TicketUpdate) -> Ticket:
        db_ticket = db.get(Ticket, id)
        if not db_ticket:
            raise NotFoundError("Ticket not found")
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

    @staticmethod
    def delete_ticket(db: Session, id: uuid.UUID) -> Ticket:
        db_ticket = db.get(Ticket, id)
        if not db_ticket:
            raise NotFoundError("Ticket not found")
        db.delete(db_ticket)
        db.commit()
        return db_ticket
