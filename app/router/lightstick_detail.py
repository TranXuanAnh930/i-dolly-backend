from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.lightstick_detail import LightstickDetailCreate, LightstickDetailUpdate, LightstickDetailRead
from app.services.lightstick_detail_service import (
    add_lightstick_detail, get_lightstick_details, get_lightstick_detail,
    update_lightstick_detail, delete_lightstick_detail,
)
from app.exception.db_triggers import TriggerViolationError

router = APIRouter(prefix="/lightstick_details", tags=["Lightstick Details"])

def _raise_for(result, not_found_detail: str):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage lightstick details for their own company's idols/groups")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "conflict":
        raise HTTPException(status_code=400, detail="This product already has lightstick details")

@router.post("/add", response_model=LightstickDetailRead)
async def add_new_lightstick_detail(data: LightstickDetailCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    try:
        result = add_lightstick_detail(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    if isinstance(result, str):
        _raise_for(result, "Product, idol, group, or color not found")
    return result

@router.get("/all", response_model=List[LightstickDetailRead])
async def list_lightstick_details(db: Session = Depends(get_db)):
    result = get_lightstick_details(db)
    if not result:
        raise HTTPException(status_code=404, detail="No lightstick details found")
    return result

@router.get("/{product_id}", response_model=LightstickDetailRead)
async def get_lightstick_detail_by_id(product_id: int, db: Session = Depends(get_db)):
    ls = get_lightstick_detail(db, product_id)
    if not ls:
        raise HTTPException(status_code=404, detail="Lightstick details not found")
    return ls

@router.put("/update/{product_id}", response_model=LightstickDetailRead)
async def update_existing_lightstick_detail(product_id: int, data: LightstickDetailUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = update_lightstick_detail(db, product_id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Lightstick details not found")
    return result

@router.delete("/delete/{product_id}")
async def delete_existing_lightstick_detail(product_id: int, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = delete_lightstick_detail(db, product_id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Lightstick details not found")
    return {"msg": "Lightstick details deleted successfully"}
