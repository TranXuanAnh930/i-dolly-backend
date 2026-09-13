import uuid
from sqlalchemy.orm import Session, selectinload
from app.db.models.order import Order
from app.db.models.ticket import Ticket
from app.db.models.ticket_type import TicketType
from app.db.models.shipping import ShippingStatus as ModelShipStatus
from app.schema.order import OrderStatus
from app.schema.payment import PaymentCreate, PaymentGateway, PaymentStatus
from app.schema.ticket import TicketCheckoutCreate
from app.db.models.payment import Payment
from app.schema.shipping import ShippingStatus as SchemaShipStatus
from app.utils.mock_id import generate_mock_id
from app.utils.paypal_client import create_order, capture_order
from app.services.notification_service import create_notification
from app.exception.db_triggers import commit_or_raise
from app.db.models.cart import Cart
from app.db.models.products import Product
from app.db.models.order import Order, OrderItem

# Real gateway integration (Paypal or otherwise) is next-phase work — see
# docs/project_status.md. PaymentGateway currently has only one member
# (mock), kept as an enum rather than collapsed away so a real gateway has
# somewhere to slot in later without reshaping this function's contract.

def create_payment(db:Session, user_id:uuid.UUID, order:Order, data:PaymentCreate) -> Payment | bool:
    # Deliberately does not commit
    gateway = PaymentGateway(data.gateway)
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
        db.add(shipstatus)
    elif gateway == PaymentGateway.paypal:
        # Handle PayPal-specific logic here
        payment_status = PaymentStatus.pending
        pg_order_id = create_order(str(data.amount), "JPY")["id"]
        pg_payment_id = pg_signature = None
        order.status = OrderStatus.pending

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
        idempotency_key=data.idempotency_key,
    )
    db.add(payment)
    db.flush()
    return payment

def create_ticket_payment(db:Session, user_id:uuid.UUID, ticket:Ticket, data:TicketCheckoutCreate) -> Payment | bool:
    # Deliberately does not commit
    # caller (ticket_service.checkout_ticket) holds a row lock on the
    # ticket_type for the whole operation and commits once at the end, so
    # the lock is never released mid-flow the way order_service.checkout's
    # commit here does (see docs/project_status.md §4 item 1 — the exact
    # race this avoids repeating in new code).
    #
    # Requires ticket.id already populated (the caller flushes right after
    # adding the ticket) — this sets payment.ticket_id below, the column
    # that lets a payment say what it was for without a reverse scan of
    # tickets.payment_id.
    gateway = PaymentGateway(data.gateway)
    payment_status = PaymentStatus.pending
    if gateway == PaymentGateway.mock:
        is_success = data.simulate_succ
        if not is_success:
            payment_status = PaymentStatus.failed
            pg_order_id = pg_payment_id = pg_signature = None
            ticket.status = "cancelled"
        else:
            payment_status = PaymentStatus.success
            ids = generate_mock_id()
            pg_order_id = ids["order_id"]
            pg_payment_id = ids["payment_id"]
            pg_signature = ids["signature_id"]
            ticket.status = "paid"
    elif gateway == PaymentGateway.paypal:
        # Handle PayPal-specific logic here
        pg_order_id = create_order(str(data.amount), "JPY")["id"]
        pg_payment_id = pg_signature = None
        ticket.status = "pending_payment"

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
        idempotency_key=data.idempotency_key,
    )
    db.add(payment)
    db.flush()  # need payment.id before linking it below
    ticket.payment_id = payment.id
    return payment

def fetch_payment_status(db:Session, user_id:uuid.UUID, order_id:uuid.UUID):
    payment = db.query(Payment).filter(Payment.user_id==user_id, Payment.order_id==order_id).first()
    if not payment:
        return None
    return payment

def fetch_ticket_payment_status(db:Session, user_id:uuid.UUID, ticket_id:uuid.UUID):
    payment = db.query(Payment).filter(Payment.user_id==user_id, Payment.ticket_id==ticket_id).first()
    if not payment:
        return None
    return payment

def fetch_all_payments(db:Session, user_id:uuid.UUID):
    payment = db.query(Payment).filter(Payment.user_id==user_id).all()
    if not payment:
        return None
    return payment

def finalize_paypal_payment(db:Session, pg_order_id:str, user_id: uuid.UUID | None):
    payment = db.query(Payment).filter(Payment.pg_order_id==pg_order_id).with_for_update().first()
    if not payment or payment.status != PaymentStatus.pending or (user_id and payment.user_id!= user_id):
        return None
    if payment.ticket_id:
        ticket = db.query(Ticket).filter(Ticket.id==payment.ticket_id).with_for_update().first()
        if not ticket or ticket.status != "pending_payment" or (user_id and ticket.user_id != user_id):
            return None
        ticket_type = db.query(TicketType).filter(TicketType.id == ticket.ticket_type_id).with_for_update().first()
        if not ticket_type or ticket_type.total_quantity - ticket_type.sold_quantity <= 0 - ticket_type.sold_quantity <= 0:
            return None
        paypal_payment = capture_order(pg_order_id)
        if paypal_payment["status"] == "COMPLETED":
            payment.status = PaymentStatus.success
            ticket.status = "paid"
            ticket_type.sold_quantity += 1
            ticket.payment_id = payment.id
            create_notification(db, ticket.user_id, "ticket_confirmation", ticket_id=ticket.id)
        else:
            payment.status = PaymentStatus.failed
            ticket.status = "cancelled"
    elif payment.order_id:
        order = db.query(Order).filter(Order.id == payment.order_id).with_for_update().first()
        if not order or (user_id and order.user_id != user_id) or (order.status != OrderStatus.pending):
            return None
        paypal_payment = capture_order(pg_order_id)
        if paypal_payment["status"] == "COMPLETED":
            order_items = db.query(OrderItem).filter(OrderItem.order_id == payment.order_id).all()
            product_ids = [order_item.product_id for order_item in order_items]
            products = db.query(Product).filter(Product.id.in_(product_ids)).with_for_update().all()
            if len(order_items) == 0 or len(products) == 0:
                return None
            for product in products:
                item = next((order_item for order_item in order_items if order_item.product_id == product.id), None)
                return None
        
            for product in products:
                item = next((order_item for order_item in order_items if order_item.product_id == product.id), None)
                product.quantity-=item.quantity

            db.query(Cart).filter(Cart.user_id==payment.user_id, Cart.product_id.in_(product_ids)).delete()
            shipstatus = ModelShipStatus(order_id=order.id, status=SchemaShipStatus.pending)
            order.status = OrderStatus.confirmed
            create_notification(db, payment.user_id, "order_confirmation", order_id=order.id)
        else:
            payment.status = PaymentStatus.failed
            order.status = OrderStatus.cancelled
            shipstatus = ModelShipStatus(order_id=order.id, status=SchemaShipStatus.cancelled)
        db.add(shipstatus)
        
    commit_or_raise(db)
    return payment