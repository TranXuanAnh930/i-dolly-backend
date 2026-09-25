import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schema.events.ticket_type import SaleMethod, TicketTier, TicketTypeRead
from app.schema.marketplace import PaymentGateway


class TicketStatus(str, Enum):
    reserved = "reserved"
    pending_payment = "pending_payment"
    paid = "paid"
    cancelled = "cancelled"
    expired = "expired"
    used = "used"

class TicketCreate(BaseModel):
    """Admin-only manual ticket issue. Fans buy through /tickets/checkout; lottery winners get
    tickets from the draw."""
    ticket_type_id: uuid.UUID
    user_id: uuid.UUID
    lottery_entry_id: uuid.UUID | None = None

class TicketUpdate(BaseModel):
    status: TicketStatus | None = None
    issued_code: str | None = None
    payment_id: uuid.UUID | None = None
    payment_deadline_at: datetime | None = None

# Direct-sale ticket purchase (like PaymentCreate, without a shipping address).
class TicketCheckoutCreate(BaseModel):
    ticket_type_id: uuid.UUID
    amount: int
    gateway: PaymentGateway = PaymentGateway.mock
    simulate_succ: bool | None = None
    idempotency_key: uuid.UUID

# Payment for a ticket the lottery draw already created; the ticket id comes from the path.
class WonTicketCheckoutCreate(BaseModel):
    amount: int
    gateway: PaymentGateway = PaymentGateway.mock
    simulate_succ: bool | None = None
    idempotency_key: uuid.UUID

class TicketRead(BaseModel):
    id: uuid.UUID
    ticket_type_id: uuid.UUID
    user_id: uuid.UUID
    lottery_entry_id: uuid.UUID | None
    payment_id: uuid.UUID | None
    status: TicketStatus
    issued_code: str | None
    reserved_at: datetime
    payment_deadline_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Eager-loaded by every service that returns a TicketRead.
    ticket_type: TicketTypeRead

    model_config = {"from_attributes": True}

# --- manager sales history: one row per ticket.
class TicketSaleRead(BaseModel):
    ticket_id: uuid.UUID
    tier: TicketTier
    status: TicketStatus
    price: float
    source: SaleMethod  # derived from the ticket type's sale method
    created_at: datetime

class TicketSalesPageRead(BaseModel):
    page: int
    limit: int
    count: int
    data: list[TicketSaleRead]
