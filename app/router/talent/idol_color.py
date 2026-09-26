import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.db.models.talent import IdolColor
from app.deps.auth import require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.talent import IdolColorBase, IdolColorCreate, IdolColorRead
from app.services.talent.idol_color_service import IdolColorService

# Lookup table managers/admins can extend; delete is admin-only since colors are shared across
# companies.
router = APIRouter(prefix="/idol_colors", tags=["Idol Colors"])

# Not used by the frontend (nor is the rest of this router).
@router.post("/add", response_model=IdolColorRead)
def add_new_idol_color(color: IdolColorCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> IdolColor:
    db_color = IdolColorService.add_idol_color(db, color)
    CacheService.delete_cached_idol_colors()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_manager_products_pages()  # the product form embeds colors
    return db_color

# Not used by the frontend.
@router.get("/all", response_model=List[IdolColorRead])
def list_idol_colors(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[IdolColor]:
    result = CacheService.get_cached_idol_colors(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idol colors found")
    return result

# Not used by the frontend.
@router.put("/update/{id}", response_model=IdolColorRead)
def update_existing_idol_color(id: uuid.UUID, data: IdolColorBase, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> IdolColor:
    try:
        db_color = IdolColorService.update_idol_color(db, id, data)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_idol_colors()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_manager_products_pages()
    return db_color

# Not used by the frontend.
@router.delete("/delete/{id}", response_model=MessageResponse)
def delete_existing_idol_color(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> MessageResponse:
    result = IdolColorService.delete_idol_color(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Idol color not found")
    CacheService.delete_cached_idol_colors()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_manager_products_pages()
    return MessageResponse(msg="Idol color deleted successfully")
