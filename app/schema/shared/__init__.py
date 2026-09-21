"""Re-exports every public schema class in this domain, so callers can do `from app.schema.shared import X` instead of reaching into the individual submodule."""

from .notification import NotificationRead, NotificationStatus, NotificationType, NotificationUnreadCount

__all__ = [
    "NotificationUnreadCount",
    "NotificationRead",
    "NotificationStatus",
    "NotificationType",
]
