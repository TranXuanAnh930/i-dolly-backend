from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.album_detail import AlbumDetailCreate, AlbumDetailUpdate, AlbumDetailRead
from app.services.album_detail_service import (
    add_album_detail, get_album_details, get_album_detail, update_album_detail, delete_album_detail,
)
from app.exception.db_triggers import TriggerViolationError

router = APIRouter(prefix="/album_details", tags=["Album Details"])

def _raise_for(result, not_found_detail: str):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage album details for their own company's idols/groups")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "conflict":
        raise HTTPException(status_code=400, detail="This product already has album details")

@router.post("/add", response_model=AlbumDetailRead)
async def add_new_album_detail(data: AlbumDetailCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    try:
        result = add_album_detail(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    if isinstance(result, str):
        _raise_for(result, "Product, idol, or group not found")
    return result

@router.get("/all", response_model=List[AlbumDetailRead])
async def list_album_details(db: Session = Depends(get_db)):
    result = get_album_details(db)
    if not result:
        raise HTTPException(status_code=404, detail="No album details found")
    return result

@router.get("/{product_id}", response_model=AlbumDetailRead)
async def get_album_detail_by_id(product_id: int, db: Session = Depends(get_db)):
    album = get_album_detail(db, product_id)
    if not album:
        raise HTTPException(status_code=404, detail="Album details not found")
    return album

@router.put("/update/{product_id}", response_model=AlbumDetailRead)
async def update_existing_album_detail(product_id: int, data: AlbumDetailUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = update_album_detail(db, product_id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Album details not found")
    return result

@router.delete("/delete/{product_id}")
async def delete_existing_album_detail(product_id: int, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = delete_album_detail(db, product_id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Album details not found")
    return {"msg": "Album details deleted successfully"}
