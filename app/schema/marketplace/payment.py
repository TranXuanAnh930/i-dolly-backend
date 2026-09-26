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
    # Exactly one of order_id/ticket_id is set.
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
    # PayPal approval link for a pending PayPal payment; the buyer approves there before the
    # frontend calls POST /payment/paypal/capture/{pg_order_id}.
    pg_approval_url : str | None = None
    created_at : datetime
    updated_at : datetime

    model_config = {"from_attributes" : True}