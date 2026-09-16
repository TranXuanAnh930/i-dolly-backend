"""Re-exports every public model class in this domain, so callers can do `from app.db.models.talent import X` instead of reaching into the individual submodule."""

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
