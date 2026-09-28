"""Re-exports this domain's schema classes: `from app.schema.shared import X`."""

from .faq_answer import FaqAnswer, FaqLanguage, InstantAnswerRead, InstantAnswerRequest
from .inquiry import InquiryCreate, InquiryCreated, InquiryTopic
from .notification import NotificationRead, NotificationStatus, NotificationType, NotificationUnreadCount

__all__ = [
    "FaqAnswer",
    "FaqLanguage",
    "InstantAnswerRead",
    "InstantAnswerRequest",
    "InquiryCreate",
    "InquiryCreated",
    "InquiryTopic",
    "NotificationUnreadCount",
    "NotificationRead",
    "NotificationStatus",
    "NotificationType",
]
