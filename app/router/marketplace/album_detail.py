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
from app.schema.common import MessageResponse
from app.schema.marketplace import AlbumDetailCreate, AlbumDetailRead, AlbumDetailUpdate
from app.services.marketplace.album_detail_service import AlbumDetailService

router = APIRouter(prefix="/album_details", tags=["Album Details"])

# FRONTEND: not currently called by i-dolly-frontend — and neither is anything
# else on this router. The cart/order flow used to fetch /album_details/all and
# merge it against /products/all client-side; it now reads the
# /products/store-page bundle, which already embeds each product's album row.
# Album products themselves are created via /products/add_with_detail.
@router.post("/add", response_model=AlbumDetailRead)
async def add_new_album_detail(data: AlbumDetailCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> AlbumDetail:
    try:
        return AlbumDetailService.add_album_detail(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# FRONTEND: not currently called by i-dolly-frontend (see the note above).
@router.get("/all", response_model=List[AlbumDetailRead])
async def list_album_details(db: Session = Depends(get_db)) -> list[AlbumDetail]:
    result = AlbumDetailService.get_album_details(db)
    if not result:
        raise HTTPException(status_code=404, detail="No album details found")
    return result

# FRONTEND: not currently called by i-dolly-frontend.
@router.get("/{product_id}", response_model=AlbumDetailRead)
async def get_album_detail_by_id(product_id: uuid.UUID, db: Session = Depends(get_db)) -> AlbumDetail:
    album = AlbumDetailService.get_album_detail(db, product_id)
    if not album:
        raise HTTPException(status_code=404, detail="Album details not found")
    return album

# FRONTEND: not currently called by i-dolly-frontend.
@router.put("/update/{product_id}", response_model=AlbumDetailRead)
async def update_existing_album_detail(product_id: uuid.UUID, data: AlbumDetailUpdate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> AlbumDetail:
    try:
        return AlbumDetailService.update_album_detail(db, product_id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# FRONTEND: not currently called by i-dolly-frontend.
@router.delete("/delete/{product_id}", response_model=MessageResponse)
async def delete_existing_album_detail(product_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        AlbumDetailService.delete_album_detail(db, product_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return MessageResponse(msg="Album details deleted successfully")
