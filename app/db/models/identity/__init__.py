"""Re-exports this domain's model classes: `from app.db.models.identity import X`."""

from .refresh_token import RefreshToken
from .user import Users

__all__ = [
    "RefreshToken",
    "Users",
]
