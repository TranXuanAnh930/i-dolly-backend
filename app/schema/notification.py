import uuid
from datetime import datetime
from pydantic import BaseModel

class NotificationUnreadCount(BaseModel):
    count: int

class NotificationRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    order_id: uuid.UUID | None
    ticket_id: uuid.UUID | None
    lottery_entry_id: uuid.UUID | None
    concert_id: uuid.UUID | None
    status: str
    sent_at: datetime | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
