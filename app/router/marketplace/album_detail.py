import uuid
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity import Users
from app.db.models.marketplace import AlbumDetail
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.db_triggers import TriggerViolationError
from app.schema.marketplace import AlbumDetailCreate, AlbumDetailRead, AlbumDetailUpdate
from app.services.marketplace.album_detail_service import AlbumDetailService

router = APIRouter(prefix="/album_details", tags=["Album Details"])

def _raise_for(result: Literal["forbidden", "not_found", "conflict", "artist_inactive"], not_found_detail: str) -> None:
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage album details for their own company's idols/groups")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "conflict":
        raise HTTPException(status_code=400, detail="This product already has album details")
    if result == "artist_inactive":
        raise HTTPException(status_code=400, detail="Cannot attach a new release to a deactivated idol/group")

@router.post("/add", response_model=AlbumDetailRead)
async def add_new_album_detail(data: AlbumDetailCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> AlbumDetail:
    try:
        result = AlbumDetailService.add_album_detail(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if isinstance(result, str):
        _raise_for(result, "Product, idol, or group not found")
    return result

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
    result = AlbumDetailService.update_album_detail(db, product_id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Album details not found")
    return result

@router.delete("/delete/{product_id}")
async def delete_existing_album_detail(product_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> dict[str, str]:
    result = AlbumDetailService.delete_album_detail(db, product_id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Album details not found")
    return {"msg": "Album details deleted successfully"}
