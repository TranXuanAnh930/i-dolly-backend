"""Re-exports this domain's model classes: `from app.db.models.talent import X`."""

from .group import Group
from .idol import Idol
from .idol_color import IdolColor
from .management_company import ManagementCompany
from .position import IdolPosition, Position

__all__ = [
    "Group",
    "Idol",
    "IdolColor",
    "ManagementCompany",
    "Position",
    "IdolPosition",
]
