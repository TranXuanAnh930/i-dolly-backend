import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class NotificationType(str, Enum):
    order_confirmation = "order_confirmation"
    ticket_confirmation = "ticket_confirmation"
    lottery_registered = "lottery_registered"
    lottery_draw_triggered = "lottery_draw_triggered"
    lottery_draw_failed = "lottery_draw_failed"
    lottery_result = "lottery_result"
    lottery_payment_reminder = "lottery_payment_reminder"
    lottery_payment_confirmation = "lottery_payment_confirmation"
    event_reminder = "event_reminder"
    password_reset = "password_reset"

class NotificationStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"

class NotificationUnreadCount(BaseModel):
    count: int

class NotificationRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: NotificationType
    order_id: uuid.UUID | None
    ticket_id: uuid.UUID | None
    lottery_entry_id: uuid.UUID | None
    concert_id: uuid.UUID | None
    status: NotificationStatus
    sent_at: datetime | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
