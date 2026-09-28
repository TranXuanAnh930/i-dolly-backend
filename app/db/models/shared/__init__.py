"""Re-exports this domain's model classes: `from app.db.models.shared import X`."""

from .inquiry import Inquiry
from .notification import Notification

__all__ = [
    "Inquiry",
    "Notification",
]
