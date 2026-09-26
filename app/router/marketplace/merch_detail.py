import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity import Users
from app.db.models.marketplace import MerchDetail
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.exception.db_triggers import TriggerViolationError
from app.schema.common import MessageResponse
from app.schema.marketplace import MerchDetailCreate, MerchDetailRead, MerchDetailUpdate
from app.services.marketplace.merch_detail_service import MerchDetailService

router = APIRouter(prefix="/merch_details", tags=["Merch Details"])

# Not used by the frontend (nor is the rest of this router).
@router.post("/add", response_model=MerchDetailRead)
def add_new_merch_detail(data: MerchDetailCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MerchDetail:
    try:
        return MerchDetailService.add_merch_detail(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.get("/all", response_model=List[MerchDetailRead])
def list_merch_details(db: Session = Depends(get_db)) -> list[MerchDetail]:
    result = MerchDetailService.get_merch_details(db)
    if not result:
        raise HTTPException(status_code=404, detail="No merch details found")
    return result

# Not used by the frontend.
@router.get("/{product_id}", response_model=MerchDetailRead)
def get_merch_detail_by_id(product_id: uuid.UUID, db: Session = Depends(get_db)) -> MerchDetail:
    md = MerchDetailService.get_merch_detail(db, product_id)
    if not md:
        raise HTTPException(status_code=404, detail="Merch details not found")
    return md

# Not used by the frontend.
@router.put("/update/{product_id}", response_model=MerchDetailRead)
def update_existing_merch_detail(product_id: uuid.UUID, data: MerchDetailUpdate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MerchDetail:
    try:
        return MerchDetailService.update_merch_detail(db, product_id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.delete("/delete/{product_id}", response_model=MessageResponse)
def delete_existing_merch_detail(product_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        MerchDetailService.delete_merch_detail(db, product_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return MessageResponse(msg="Merch details deleted successfully")
