"""Re-exports every public model class in this domain, so callers can do `from app.db.models.shared import X` instead of reaching into the individual submodule."""

from .notification import Notification, notification_status_enum, notification_type_enum

__all__ = [
    "notification_type_enum",
    "notification_status_enum",
    "Notification",
]
