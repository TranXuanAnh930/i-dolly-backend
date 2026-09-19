import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.db.models.events import Ticket, TicketType
from app.db.models.marketplace import Cart, Order, OrderItem, Payment, Product
from app.db.models.marketplace import ShippingStatus as ModelShipStatus
from app.exception.db_triggers import commit_or_raise
from app.schema.events import TicketCheckoutCreate, WonTicketCheckoutCreate
from app.schema.marketplace import OrderStatus, PaymentCreate, PaymentGateway, PaymentStatus
from app.schema.marketplace import ShippingStatus as SchemaShipStatus
from app.services.shared.notification_service import NotificationService
from app.utils.mock_id import generate_mock_id
from app.utils.paypal_client import capture_order, create_order, extract_approval_url


class PaymentService:

    @staticmethod
    def create_payment(db:Session, user_id:uuid.UUID, order:Order, data:PaymentCreate) -> Payment:
        # Deliberately does not commit
        gateway = PaymentGateway(data.gateway)
        pg_approval_url = None
        if gateway == PaymentGateway.mock:
            is_success = data.simulate_succ
            if not is_success:
                payment_status = PaymentStatus.failed
                pg_order_id = pg_payment_id = pg_signature = None
                order.status = OrderStatus.cancelled
                shipstatus = ModelShipStatus(order_id=order.id, status=SchemaShipStatus.cancelled)
            else:
                payment_status = PaymentStatus.success
                ids = generate_mock_id()
                pg_order_id = ids["order_id"]
                pg_payment_id = ids["payment_id"]
                pg_signature = ids["signature_id"]
                order.status = OrderStatus.confirmed
                shipstatus = ModelShipStatus(order_id=order.id, status=SchemaShipStatus.pending)
        elif gateway == PaymentGateway.paypal:
            # Handle PayPal-specific logic here
            payment_status = PaymentStatus.pending
            order_response = create_order(str(data.amount), "JPY")
            pg_order_id = order_response["id"]
            pg_approval_url = extract_approval_url(order_response)
            pg_payment_id = pg_signature = None
            order.status = OrderStatus.pending
            shipstatus = ModelShipStatus(order_id=order.id, status=SchemaShipStatus.pending)

        db.add(shipstatus)
        payment = Payment(
            order_id=order.id,
            user_id=user_id,
            amount=data.amount,
            status=payment_status,
            payment_gateway=gateway,
            is_paid=(payment_status == PaymentStatus.success),
            pg_order_id=pg_order_id,
            pg_payment_id=pg_payment_id,
            pg_signature=pg_signature,
            pg_approval_url=pg_approval_url,
            idempotency_key=data.idempotency_key,
        )
        db.add(payment)
        db.flush()
        return payment

    @staticmethod
    def create_ticket_payment(db:Session, user_id:uuid.UUID, ticket:Ticket, data:TicketCheckoutCreate | WonTicketCheckoutCreate) -> Payment:
        # Deliberately does not commit — the caller holds a row lock on ticket_type for the whole
        # operation and commits once at the end, so the lock is never released mid-flow. Requires
        # ticket.id already populated (the caller flushes right after adding the ticket).
        gateway = PaymentGateway(data.gateway)
        payment_status = PaymentStatus.pending
        pg_approval_url = None
        if gateway == PaymentGateway.mock:
            is_success = data.simulate_succ
            if not is_success:
                if ticket.ticket_type.sale_method == "direct":
                    ticket.status = "cancelled"
                payment_status = PaymentStatus.failed
                pg_order_id = pg_payment_id = pg_signature = None

            else:
                payment_status = PaymentStatus.success
                ids = generate_mock_id()
                pg_order_id = ids["order_id"]
                pg_payment_id = ids["payment_id"]
                pg_signature = ids["signature_id"]
                ticket.status = "paid"
        elif gateway == PaymentGateway.paypal:
            # Handle PayPal-specific logic here
            order_response = create_order(str(data.amount), "JPY")
            pg_order_id = order_response["id"]
            pg_approval_url = extract_approval_url(order_response)
            pg_payment_id = pg_signature = None

        payment = Payment(
            order_id=None,
            ticket_id=ticket.id,
            user_id=user_id,
            amount=data.amount,
            status=payment_status,
            payment_gateway=gateway,
            is_paid=(payment_status == PaymentStatus.success),
            pg_order_id=pg_order_id,
            pg_payment_id=pg_payment_id,
            pg_signature=pg_signature,
            pg_approval_url=pg_approval_url,
            idempotency_key=data.idempotency_key,
        )
        db.add(payment)
        db.flush()  # need payment.id before linking it below
        ticket.payment_id = payment.id
        return payment

    @staticmethod
    def fetch_payment_status(db:Session, user_id:uuid.UUID, order_id:uuid.UUID) -> Payment | None:
        payment = db.query(Payment).filter(Payment.user_id==user_id, Payment.order_id==order_id).first()
        if not payment:
            return None
        return payment

    @staticmethod
    def fetch_ticket_payment_status(db:Session, user_id:uuid.UUID, ticket_id:uuid.UUID) -> Payment | None:
        payment = db.query(Payment).filter(Payment.user_id==user_id, Payment.ticket_id==ticket_id).first()
        if not payment:
            return None
        return payment

    @staticmethod
    def fetch_all_payments(db:Session, user_id:uuid.UUID) -> list[Payment] | None:
        payment = db.query(Payment).filter(Payment.user_id==user_id).all()
        if not payment:
            return None
        return payment

    @staticmethod
    def finalize_paypal_payment(db:Session, pg_order_id:str, user_id: uuid.UUID | None = None) -> Payment | None:
        payment = db.query(Payment).filter(Payment.pg_order_id==pg_order_id).with_for_update().first()
        if not payment or payment.status != PaymentStatus.pending or (user_id and payment.user_id!= user_id):
            return None
        if payment.ticket_id:
            ticket = db.query(Ticket).filter(Ticket.id==payment.ticket_id).with_for_update().first()
            if not ticket or ticket.status != "pending_payment" or (user_id and ticket.user_id != user_id):
                return None
            ticket_type = db.query(TicketType).filter(TicketType.id == ticket.ticket_type_id).with_for_update().first()
            if not ticket_type:
                return None
            if ticket_type.sale_method == "direct" and ticket_type.total_quantity - ticket_type.sold_quantity <= 0:
                return None        
            elif ticket_type.sale_method == "lottery":
                if ticket.payment_deadline_at and ticket.payment_deadline_at < datetime.now(timezone.utc):
                    # Lazily discovered past the deadline — no sweep job exists yet
                    # (database-design.md §5.2's "deliberately not built this phase")
                    # to release this slot otherwise, so this is the one place that
                    # does it: expire the ticket and free the seat it was holding.
                    ticket.status = "expired"
                    ticket_type.sold_quantity -= 1
                    commit_or_raise(db)
                    return None

            paypal_payment = capture_order(pg_order_id)
            if paypal_payment["status"] == "COMPLETED":
                payment.status = PaymentStatus.success
                payment.is_paid = True
                ids = generate_mock_id()
                payment.pg_payment_id = ids["payment_id"]
                payment.pg_signature = ids["signature_id"]
                ticket.status = "paid"
                ticket.payment_id = payment.id
                if ticket_type.sale_method == "direct":
                    ticket_type.sold_quantity += 1        
                    NotificationService.create_notification(db, ticket.user_id, "ticket_confirmation", ticket_id=ticket.id)
                elif ticket_type.sale_method == "lottery":
                    NotificationService.create_notification(db, ticket.user_id, "lottery_payment_confirmation", ticket_id=ticket.id)
            else:
                payment.status = PaymentStatus.failed
                if ticket_type.sale_method == "direct":
                    ticket.status = "cancelled"
        elif payment.order_id:
            order = db.query(Order).filter(Order.id == payment.order_id).with_for_update().first()
            if not order or (user_id and order.user_id != user_id) or (order.status != OrderStatus.pending):
                return None
            order_items = db.query(OrderItem).filter(OrderItem.order_id == payment.order_id).all()
            product_ids = [order_item.product_id for order_item in order_items]
            products = db.query(Product).filter(Product.id.in_(product_ids)).with_for_update().all()
            if len(order_items) == 0 or len(products) == 0:
                return None
            for product in products:
                item = next((order_item for order_item in order_items if order_item.product_id == product.id), None)
                if product.quantity < item.quantity:
                    return None
            paypal_payment = capture_order(pg_order_id)
            if paypal_payment["status"] == "COMPLETED":
                payment.status = PaymentStatus.success
                payment.is_paid = True
                ids = generate_mock_id()
                payment.pg_payment_id = ids["payment_id"]
                payment.pg_signature = ids["signature_id"]

                for product in products:
                    item = next((order_item for order_item in order_items if order_item.product_id == product.id), None)
                    product.quantity-=item.quantity

                db.query(Cart).filter(Cart.user_id==payment.user_id, Cart.product_id.in_(product_ids)).delete()
                shipstatus = ModelShipStatus(order_id=order.id, status=SchemaShipStatus.pending)
                order.status = OrderStatus.confirmed
                NotificationService.create_notification(db, payment.user_id, "order_confirmation", order_id=order.id)
            else:
                payment.status = PaymentStatus.failed
                order.status = OrderStatus.cancelled
                shipstatus = ModelShipStatus(order_id=order.id, status=SchemaShipStatus.cancelled)
            db.add(shipstatus)

        commit_or_raise(db)
        if payment.status == PaymentStatus.success:
            CacheService.delete_cached_products()
        return payment
