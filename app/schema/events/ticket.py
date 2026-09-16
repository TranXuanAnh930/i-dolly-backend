import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schema.events.ticket_type import TicketTypeRead
from app.schema.marketplace import PaymentGateway


class TicketCreate(BaseModel):
    """ADMIN-ONLY STOPGAP (database-design.md §7.4): the draw-job flow that
    should issue a ticket to a lottery winner doesn't exist yet. This lets an
    admin manually issue a ticket in the meantime — it is NOT the intended
    long-term creation path for that case and should be replaced once the
    draw job lands. Direct-sale purchases no longer go through this: see
    ticket_service.checkout_ticket / POST /tickets/checkout."""
    ticket_type_id: uuid.UUID
    user_id: uuid.UUID
    lottery_entry_id: uuid.UUID | None = None

class TicketUpdate(BaseModel):
    status: str | None = None  # 'reserved' | 'pending_payment' | 'paid' | 'cancelled' | 'expired' | 'used'
    issued_code: str | None = None
    payment_id: uuid.UUID | None = None
    payment_deadline_at: datetime | None = None

# A fan buying a direct-sale ticket, mirroring PaymentCreate — no
# shipping_address_id, since a ticket has nothing to ship.
class TicketCheckoutCreate(BaseModel):
    ticket_type_id: uuid.UUID
    amount: int
    gateway: PaymentGateway = PaymentGateway.mock
    simulate_succ: bool | None = None
    idempotency_key: uuid.UUID

# A lottery winner paying for the ticket draw_lottery already created for
# them (status="pending_payment", lottery_entry_id set) — no ticket_type_id
# here, unlike TicketCheckoutCreate, since the ticket (and its type) already
# exist; the path param identifies which one.
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
    status: str
    issued_code: str | None
    reserved_at: datetime
    payment_deadline_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Eager-loaded by every service function that returns a TicketRead
    # (get_ticket/get_my_tickets/checkout_ticket) — same reasoning as
    # Order.items on the order side: the frontend's ticket detail/history
    # views need tier/price/concert_id and shouldn't have to make a second
    # round trip for it.
    ticket_type: TicketTypeRead

    model_config = {"from_attributes": True}

# --- manager-facing sales history (mirrors ProductSaleRead/ProductSalesPageRead
# in schema/products.py) — one row per ticket, not per order, since a ticket
# has no order/line-item concept of its own.
class TicketSaleRead(BaseModel):
    ticket_id: uuid.UUID
    tier: str
    status: str
    price: float
    source: str  # 'lottery' | 'direct' — derived from lottery_entry_id, not a stored column
    created_at: datetime

class TicketSalesPageRead(BaseModel):
    page: int
    limit: int
    count: int
    data: list[TicketSaleRead]
