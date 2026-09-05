import uuid
from sqlalchemy.orm import Session
from app.db.models.order import Order
from app.db.models.shipping import ShippingStatus as ModelShipStatus
from app.schema.order import OrderStatus
from app.schema.payment import PaymentCreate, PaymentGateway, PaymentStatus
from app.db.models.payment import Payment
from app.schema.shipping import ShippingStatus as SchemaShipStatus
from app.utils.mock_id import generate_mock_id

# Real gateway integration (Razorpay or otherwise) is next-phase work — see
# docs/project_status.md. PaymentGateway currently has only one member
# (mock), kept as an enum rather than collapsed away so a real gateway has
# somewhere to slot in later without reshaping this function's contract.

def create_payment(db:Session, user_id:uuid.UUID, order:Order, data:PaymentCreate) -> Payment | bool:
    gateway = PaymentGateway(data.gateway)
    if gateway != PaymentGateway.mock:
        return False

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

    payment = Payment(
        order_id=order.id,
        user_id=user_id,
        amount=data.amount,
        status=payment_status,
        payment_gateway=gateway,
        is_paid=(payment_status == PaymentStatus.success),
        pg_order_id=pg_order_id,
        pg_payment_id=pg_payment_id,
        pg_signature=pg_signature
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment

def fetch_payment_status(db:Session, user_id:uuid.UUID, order_id:uuid.UUID):
    payment = db.query(Payment).filter(Payment.user_id==user_id, Payment.order_id==order_id).first()
    if not payment:
        return None
    return payment

def fetch_all_payments(db:Session, user_id:uuid.UUID):
    payment = db.query(Payment).filter(Payment.user_id==user_id).all()
    if not payment:
        return None
    return payment
