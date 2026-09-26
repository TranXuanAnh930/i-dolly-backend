"""Re-exports this domain's schema classes: `from app.schema.talent import X`."""

from .group import (
    GroupBase,
    GroupCreate,
    GroupDetailRead,
    GroupRead,
    GroupsPageRead,
    GroupUpdate,
    GroupWithCount,
    ManagerGroupsPageRead,
)
from .idol import (
    GroupMini,
    GroupOptionForCompany,
    IdolBase,
    IdolCreate,
    IdolDetailGroup,
    IdolDetailRead,
    IdolRead,
    IdolUpdate,
    IdolWithPositions,
    ManagerIdolFormPageRead,
    ManagerIdolsPageRead,
    MembersPageRead,
)
from .idol_color import IdolColorBase, IdolColorCreate, IdolColorRead
from .management_company import ManagementCompanyBase, ManagementCompanyCreate, ManagementCompanyRead
from .position import IdolPositionAssign, IdolPositionRead, PositionBase, PositionCreate, PositionRead

__all__ = [
    "GroupBase",
    "GroupCreate",
    "GroupUpdate",
    "GroupRead",
    "GroupWithCount",
    "GroupsPageRead",
    "GroupDetailRead",
    "ManagerGroupsPageRead",
    "IdolBase",
    "IdolCreate",
    "IdolUpdate",
    "IdolRead",
    "GroupMini",
    "IdolWithPositions",
    "MembersPageRead",
    "IdolDetailGroup",
    "IdolDetailRead",
    "ManagerIdolsPageRead",
    "GroupOptionForCompany",
    "ManagerIdolFormPageRead",
    "IdolColorBase",
    "IdolColorCreate",
    "IdolColorRead",
    "ManagementCompanyBase",
    "ManagementCompanyCreate",
    "ManagementCompanyRead",
    "PositionBase",
    "PositionCreate",
    "PositionRead",
    "IdolPositionAssign",
    "IdolPositionRead",
]
