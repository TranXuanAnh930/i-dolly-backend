import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session, selectinload

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

# ADMIN-ONLY STOPGAP for create/update/delete — see TicketCreate's docstring.
# Fans only ever read their own tickets here. Mirrors
# trg_tickets_one_per_concert (schema.sql) at the service layer.

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
    @staticmethod
    def checkout_ticket(db: Session, user_id: uuid.UUID, data: TicketCheckoutCreate) -> Ticket:
        user = db.get(Users, user_id)
        if not user or user.role != UserRole.fan:
            # Primary check for trg_tickets_fan_only — the trigger is the
            # backstop (see flush_or_raise below), same split as
            # order_service.checkout's own FanOnlyPurchaseError check.
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
            # Primary check for trg_tickets_one_per_concert — same reasoning as
            # add_ticket's own pre-check below.
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
        flush_or_raise(db)  # trg_tickets_fan_only / trg_tickets_one_per_concert backstop — also populates ticket.id for create_ticket_payment below

        payment = PaymentService.create_ticket_payment(db, user_id, ticket, data)
        if not payment:
            raise UnsupportedGatewayError("Unsupported payment gateway!")
        if payment.status == PaymentStatus.success:
            if ticket.status == TicketStatus.paid:
                ticket_type.sold_quantity += 1
                NotificationService.create_notification(db, user_id, NotificationType.ticket_confirmation, ticket_id=ticket.id)
                email_body = EmailTemplate.TICKET_CONFIRMED.render(
                    email=user.email, ticket_id=ticket.id, tier=ticket_type.tier, price=ticket_type.price
                )
                celery_app.send_task("app.tasks.email.send_email", args=[user.email, EmailTemplate.TICKET_CONFIRMED.subject, email_body])
        commit_or_raise(db)  # trg_tickets_fan_only / trg_tickets_one_per_concert / chk_ticket_types_capacity backstop
        db.refresh(ticket)
        return ticket

    # Pays for a ticket draw_lottery already created (sold_quantity already incremented at draw
    # time) — distinct from checkout_ticket above, which creates a new ticket and counts
    # sold_quantity itself. Deliberately doesn't touch sold_quantity here, to avoid double-counting
    # a seat the caller already holds.
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
            # Lazily discovered past the deadline — no sweep job exists yet
            # (database-design.md §5.2's "deliberately not built this phase")
            # to release this slot otherwise, so this is the one place that
            # does it: expire the ticket and free the seat it was holding.
            ticket.status = TicketStatus.expired
            ticket_type.sold_quantity -= 1
            commit_or_raise(db)
            raise TicketNotPayableError("The payment deadline for this ticket has passed")

        total_amount = with_tax(float(ticket_type.price))
        if data.amount != total_amount:
            raise PaymentAmountMismatch("Payment amount does not match ticket price!")

        payment = PaymentService.create_ticket_payment(db, user_id, ticket, data)
        if not payment:
            raise UnsupportedGatewayError("Unsupported payment gateway!")
        if payment.status == PaymentStatus.success:
            NotificationService.create_notification(db, user_id, NotificationType.lottery_payment_confirmation, ticket_id=ticket.id)
            user = db.get(Users, user_id)
            if user:
                email_body = EmailTemplate.LOTTERY_PAYMENT_CONFIRMED.render(
                    email=user.email, ticket_id=ticket.id, tier=ticket_type.tier, price=ticket_type.price
                )
                celery_app.send_task(
                    "app.tasks.email.send_email", args=[user.email, EmailTemplate.LOTTERY_PAYMENT_CONFIRMED.subject, email_body]
                )

        commit_or_raise(db)
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
            # Primary check for trg_tickets_fan_only — checks the ticket's
            # intended owner (data.user_id), not the caller, since this
            # endpoint is admin-only (an admin issuing a ticket to a fan).
            raise ForbiddenError("Tickets can only be issued to fan accounts")
        if data.lottery_entry_id is not None and not db.get(LotteryEntry, data.lottery_entry_id):
            raise NotFoundError("Lottery entry not found")

        if TicketService._existing_live_ticket(db, data.user_id, ticket_type.concert_id):
            raise BadRequestError("This user already holds a live ticket for this concert")  # trg_tickets_one_per_concert: one live ticket per user per concert

        db_ticket = Ticket(
            ticket_type_id=data.ticket_type_id, user_id=data.user_id, lottery_entry_id=data.lottery_entry_id,
        )
        db.add(db_ticket)
        commit_or_raise(db)  # trg_tickets_fan_only / trg_tickets_one_per_concert backstop
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

    # Company-scoped via the concert (Ticket -> TicketType -> Concert.company_id),
    # same pattern as concert_service/ticket_type_service. Mirrors
    # product_service.get_product_sales_page's shape (page/limit/count/data) for
    # the manager-facing "sales history" list/page pair.
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
