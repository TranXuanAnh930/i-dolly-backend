"""Re-exports this domain's schema classes: `from app.schema.shared import X`."""

from .notification import NotificationRead, NotificationStatus, NotificationType, NotificationUnreadCount

__all__ = [
    "NotificationUnreadCount",
    "NotificationRead",
    "NotificationStatus",
    "NotificationType",
]
