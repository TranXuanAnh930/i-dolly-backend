import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel

class PaymentStatus(str, Enum):
    pending = "pending"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"

class PaymentGateway(Enum):
    mock = "mock"
    paypal = "paypal"

class PaymentCreate(BaseModel):
    amount : int
    shipping_address_id : uuid.UUID
    gateway : PaymentGateway = PaymentGateway.mock
    simulate_succ : bool | None = None
    idempotency_key: uuid.UUID

class PaymentResponse(BaseModel):
    id : uuid.UUID
    # Exactly one of these is set — order_id for a store checkout
    # (order_service.checkout), ticket_id for a direct-sale ticket
    # (ticket_service.checkout_ticket). order_id used to be required here,
    # which meant serializing a ticket payment (order_id always null) raised
    # a validation error — fetch_all_payments would 500 for any user who'd
    # ever bought a ticket.
    order_id : uuid.UUID | None = None
    ticket_id : uuid.UUID | None = None
    user_id : uuid.UUID
    amount : int
    status : PaymentStatus
    payment_gateway : PaymentGateway
    is_paid : bool
    pg_order_id : str | None
    pg_payment_id : str | None
    pg_signature : str | None
    created_at : datetime
    updated_at : datetime

    model_config = {"from_attributes" : True}