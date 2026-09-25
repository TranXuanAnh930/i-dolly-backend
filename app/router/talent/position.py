import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.db.models.talent import IdolPosition, Position
from app.deps.auth import require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.talent import IdolPositionAssign, IdolPositionRead, PositionBase, PositionCreate, PositionRead
from app.services.talent.position_service import PositionService

# Lookup table managers/admins can extend; delete is admin-only since positions are shared
# across companies.
router = APIRouter(prefix="/positions", tags=["Positions"])

# Not used by the frontend (nor is the rest of this router).
@router.post("/add", response_model=PositionRead)
def add_new_position(position: PositionCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Position:
    return PositionService.add_position(db, position)

# Not used by the frontend.
@router.get("/all", response_model=List[PositionRead])
def list_positions(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[Position]:
    result = PositionService.get_positions(db)
    if not result:
        raise HTTPException(status_code=404, detail="No positions found")
    return result

# Not used by the frontend.
@router.put("/update/{id}", response_model=PositionRead)
def update_existing_position(id: uuid.UUID, data: PositionBase, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Position:
    try:
        return PositionService.update_position(db, id, data)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.delete("/delete/{id}", response_model=MessageResponse)
def delete_existing_position(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> MessageResponse:
    result = PositionService.delete_position(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Position not found")
    return MessageResponse(msg="Position deleted successfully")


# --- idol_positions (join table), scoped by the linked idol's company.

# Not used by the frontend.
@router.post("/idol_positions/assign", response_model=IdolPositionRead)
def assign_position_to_idol(data: IdolPositionAssign, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> IdolPosition:
    try:
        return PositionService.assign_idol_position(db, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.get("/idol_positions/idol/{idol_id}", response_model=List[IdolPositionRead])
def list_idol_positions(idol_id: uuid.UUID, db: Session = Depends(get_db)) -> list[IdolPosition]:
    result = PositionService.get_idol_positions(db, idol_id)
    if not result:
        raise HTTPException(status_code=404, detail="This idol has no positions assigned")
    return result

# Every idol's positions in one request.
# Not used by the frontend.
@router.get("/idol_positions/all", response_model=List[IdolPositionRead])
def list_all_idol_positions(db: Session = Depends(get_db)) -> list[IdolPosition]:
    result = PositionService.get_all_idol_positions(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idol positions found")
    return result

# Not used by the frontend.
@router.put("/idol_positions/{idol_id}/{position_id}", response_model=IdolPositionRead)
def set_idol_position_primary(idol_id: uuid.UUID, position_id: uuid.UUID, is_primary: bool, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> IdolPosition:
    try:
        return PositionService.update_idol_position_primary(db, idol_id, position_id, is_primary, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.delete("/idol_positions/{idol_id}/{position_id}", response_model=MessageResponse)
def unassign_position_from_idol(idol_id: uuid.UUID, position_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        PositionService.remove_idol_position(db, idol_id, position_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return MessageResponse(msg="Position unassigned from idol successfully")
