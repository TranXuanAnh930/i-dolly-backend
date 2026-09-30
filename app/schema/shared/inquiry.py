import uuid
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class InquiryTopic(str, Enum):
    tickets = "tickets"
    lottery = "lottery"
    orders = "orders"
    payment = "payment"
    account = "account"
    other = "other"

    @property
    def label(self) -> str:
        return _TOPIC_LABELS[self]


# Shown in the confirmation email in place of anything the user typed.
_TOPIC_LABELS = {
    InquiryTopic.tickets: "Tickets",
    InquiryTopic.lottery: "Lottery",
    InquiryTopic.orders: "Orders & shipping",
    InquiryTopic.payment: "Payment",
    InquiryTopic.account: "Account",
    InquiryTopic.other: "Other",
}


class InquiryCreate(BaseModel):
    # Stripped before the length check, so whitespace-only content is rejected.
    model_config = {"str_strip_whitespace": True}

    email: EmailStr
    topic: InquiryTopic
    # 5, not more: a complete Japanese question can be very short (「返金できますか？」 is 8).
    content: str = Field(..., min_length=5, max_length=2000)


class InquiryCreated(BaseModel):
    id: uuid.UUID
    msg: str
