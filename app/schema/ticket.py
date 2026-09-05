import uuid
from datetime import datetime
from pydantic import BaseModel

class TicketCreate(BaseModel):
    """ADMIN-ONLY STOPGAP (database-design.md §7.4): the real checkout/draw-job
    flow that should create tickets (winning a lottery draw, or a direct
    purchase) doesn't exist yet. This lets an admin manually issue a ticket
    in the meantime — it is NOT the intended long-term creation path and
    should be replaced once the draw job / checkout integration lands."""
    ticket_type_id: uuid.UUID
    user_id: uuid.UUID
    lottery_entry_id: uuid.UUID | None = None

class TicketUpdate(BaseModel):
    status: str | None = None  # 'reserved' | 'pending_payment' | 'paid' | 'cancelled' | 'expired' | 'used'
    issued_code: str | None = None
    payment_id: uuid.UUID | None = None
    payment_deadline_at: datetime | None = None

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

    model_config = {"from_attributes": True}
