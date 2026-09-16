import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.deps.auth import require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.schema.talent import IdolPositionAssign, IdolPositionRead, PositionBase, PositionCreate, PositionRead
from app.services.talent.position_service import PositionService

# Same rationale as idol_colors: a lookup table, manager/admin-extensible
# without a migration (database-design.md §3.6). Delete stays admin-only for
# the same cross-company-impact reason as idol_colors.
router = APIRouter(prefix="/positions", tags=["Positions"])

@router.post("/add", response_model=PositionRead)
async def add_new_position(position: PositionCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    db_position = PositionService.add_position(db, position)
    if not db_position:
        raise HTTPException(status_code=400, detail="Invalid input")
    return db_position

@router.get("/all", response_model=List[PositionRead])
async def list_positions(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)):
    result = PositionService.get_positions(db)
    if not result:
        raise HTTPException(status_code=404, detail="No positions found")
    return result

@router.put("/update/{id}", response_model=PositionRead)
async def update_existing_position(id: uuid.UUID, data: PositionBase, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    db_position = PositionService.update_position(db, id, data)
    if not db_position:
        raise HTTPException(status_code=404, detail="Position not found")
    return db_position

@router.delete("/delete/{id}")
async def delete_existing_position(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    result = PositionService.delete_position(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"msg": "Position deleted successfully"}


# --- idol_positions (join table) — nested under /positions/idol_positions,
# rather than its own top-level router, since it has no independent identity
# outside the (idol, position) pair it links. Company-scoped by the idol the
# link belongs to, same as groups/idols (position_service._manager_scope_
# violation, checked against link.idol.company_id / idol.company_id).

def _raise_for_link(result, not_found_detail: str):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage positions for idols in their own company")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "conflict":
        raise HTTPException(status_code=400, detail="Idol already has this position — use PUT to change is_primary")

@router.post("/idol_positions/assign", response_model=IdolPositionRead)
async def assign_position_to_idol(data: IdolPositionAssign, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = PositionService.assign_idol_position(db, data, current_user)
    if isinstance(result, str):
        _raise_for_link(result, "Idol or position not found")
    return result

@router.get("/idol_positions/idol/{idol_id}", response_model=List[IdolPositionRead])
async def list_idol_positions(idol_id: uuid.UUID, db: Session = Depends(get_db)):
    result = PositionService.get_idol_positions(db, idol_id)
    if not result:
        raise HTTPException(status_code=404, detail="This idol has no positions assigned")
    return result

# Bulk read — lets a client building a members grid (or any other view
# needing every idol's positions) fetch them in one request instead of one
# per idol.
@router.get("/idol_positions/all", response_model=List[IdolPositionRead])
async def list_all_idol_positions(db: Session = Depends(get_db)):
    result = PositionService.get_all_idol_positions(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idol positions found")
    return result

@router.put("/idol_positions/{idol_id}/{position_id}", response_model=IdolPositionRead)
async def set_idol_position_primary(idol_id: uuid.UUID, position_id: uuid.UUID, is_primary: bool, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = PositionService.update_idol_position_primary(db, idol_id, position_id, is_primary, current_user)
    if isinstance(result, str):
        _raise_for_link(result, "This idol/position assignment doesn't exist")
    return result

@router.delete("/idol_positions/{idol_id}/{position_id}")
async def unassign_position_from_idol(idol_id: uuid.UUID, position_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = PositionService.remove_idol_position(db, idol_id, position_id, current_user)
    if isinstance(result, str):
        _raise_for_link(result, "This idol/position assignment doesn't exist")
    return {"msg": "Position unassigned from idol successfully"}
