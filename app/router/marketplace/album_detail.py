import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity import Users
from app.db.models.marketplace import AlbumDetail
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.exception.db_triggers import TriggerViolationError
from app.schema.marketplace import AlbumDetailCreate, AlbumDetailRead, AlbumDetailUpdate
from app.services.marketplace.album_detail_service import AlbumDetailService

router = APIRouter(prefix="/album_details", tags=["Album Details"])

@router.post("/add", response_model=AlbumDetailRead)
async def add_new_album_detail(data: AlbumDetailCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> AlbumDetail:
    try:
        return AlbumDetailService.add_album_detail(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.get("/all", response_model=List[AlbumDetailRead])
async def list_album_details(db: Session = Depends(get_db)) -> list[AlbumDetail]:
    result = AlbumDetailService.get_album_details(db)
    if not result:
        raise HTTPException(status_code=404, detail="No album details found")
    return result

@router.get("/{product_id}", response_model=AlbumDetailRead)
async def get_album_detail_by_id(product_id: uuid.UUID, db: Session = Depends(get_db)) -> AlbumDetail:
    album = AlbumDetailService.get_album_detail(db, product_id)
    if not album:
        raise HTTPException(status_code=404, detail="Album details not found")
    return album

@router.put("/update/{product_id}", response_model=AlbumDetailRead)
async def update_existing_album_detail(product_id: uuid.UUID, data: AlbumDetailUpdate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> AlbumDetail:
    try:
        return AlbumDetailService.update_album_detail(db, product_id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.delete("/delete/{product_id}")
async def delete_existing_album_detail(product_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        AlbumDetailService.delete_album_detail(db, product_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return {"msg": "Album details deleted successfully"}
