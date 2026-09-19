import uuid
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity import Users
from app.db.models.marketplace import MerchDetail
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.db_triggers import TriggerViolationError
from app.schema.marketplace import MerchDetailCreate, MerchDetailRead, MerchDetailUpdate
from app.services.marketplace.merch_detail_service import MerchDetailService

router = APIRouter(prefix="/merch_details", tags=["Merch Details"])

def _raise_for(result: Literal["forbidden", "not_found", "conflict", "artist_inactive"], not_found_detail: str) -> None:
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage merch details for their own company's idols/groups")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "conflict":
        raise HTTPException(status_code=400, detail="This product already has merch details")
    if result == "artist_inactive":
        raise HTTPException(status_code=400, detail="Cannot attach new merch to a deactivated idol/group")

@router.post("/add", response_model=MerchDetailRead)
async def add_new_merch_detail(data: MerchDetailCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MerchDetail:
    try:
        result = MerchDetailService.add_merch_detail(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if isinstance(result, str):
        _raise_for(result, "Product, idol, group, or color not found")
    return result

@router.get("/all", response_model=List[MerchDetailRead])
async def list_merch_details(db: Session = Depends(get_db)) -> list[MerchDetail]:
    result = MerchDetailService.get_merch_details(db)
    if not result:
        raise HTTPException(status_code=404, detail="No merch details found")
    return result

@router.get("/{product_id}", response_model=MerchDetailRead)
async def get_merch_detail_by_id(product_id: uuid.UUID, db: Session = Depends(get_db)) -> MerchDetail:
    md = MerchDetailService.get_merch_detail(db, product_id)
    if not md:
        raise HTTPException(status_code=404, detail="Merch details not found")
    return md

@router.put("/update/{product_id}", response_model=MerchDetailRead)
async def update_existing_merch_detail(product_id: uuid.UUID, data: MerchDetailUpdate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MerchDetail:
    result = MerchDetailService.update_merch_detail(db, product_id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Merch details not found")
    return result

@router.delete("/delete/{product_id}")
async def delete_existing_merch_detail(product_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> dict[str, str]:
    result = MerchDetailService.delete_merch_detail(db, product_id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Merch details not found")
    return {"msg": "Merch details deleted successfully"}
