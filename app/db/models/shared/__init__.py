"""Re-exports every public model class in this domain, so callers can do `from app.db.models.shared import X` instead of reaching into the individual submodule."""

from .notification import Notification

__all__ = [
    "Notification",
]
