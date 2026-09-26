import uuid
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.db.models.talent import Idol
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.talent import (
    IdolCreate,
    IdolDetailRead,
    IdolRead,
    IdolUpdate,
    ManagerIdolFormPageRead,
    ManagerIdolsPageRead,
    MembersPageRead,
)
from app.services.talent.idol_service import IdolService
from app.utils.storage import StorageError, get_storage

# Managers can only manage their own company's idols. Writes can fail with 403 (wrong company),
# 404 (missing reference) or 400 (group belongs to another company, or is inactive).
router = APIRouter(prefix="/idols", tags=["Idols"])

# multipart/form-data (profile fields plus an optional image file).
@router.post("/add", response_model=IdolRead)
def add_new_idol(
    name: str = Form(...),
    company_id: uuid.UUID = Form(...),
    group_id: uuid.UUID | None = Form(None),
    date_of_birth: date | None = Form(None),
    hometown: str | None = Form(None),
    color_id: uuid.UUID | None = Form(None),
    short_intro: str | None = Form(None),
    long_description: str | None = Form(None),
    image: UploadFile | None = File(None),
    current_user: Users = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
) -> Idol:
    profile_image_url = None
    if image is not None:
        try:
            profile_image_url = get_storage().save(image, subfolder="idols")
        except StorageError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    idol = IdolCreate(
        name=name, company_id=company_id, group_id=group_id, date_of_birth=date_of_birth,
        hometown=hometown, color_id=color_id, short_intro=short_intro,
        long_description=long_description, profile_image_url=profile_image_url,
    )
    try:
        result = IdolService.add_idol(db, idol, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_groups_page()  # member_count changed
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_idol_details()  # sibling lists changed
    CacheService.delete_cached_group_details()  # member lists changed
    return result

# Not used by the frontend.
@router.get("/all", response_model=List[IdolRead])
def list_idols(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[Idol]:
    result = IdolService.get_idols(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idols found")
    return result

# Page-shaped reads. Registered before /{id} so these paths aren't parsed as an id.
@router.get("/members-page", response_model=MembersPageRead)
def get_members_page_data(db: Session = Depends(get_db)) -> MembersPageRead:
    result = CacheService.get_cached_members_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idols found")
    return result

@router.get("/{id}/detail", response_model=IdolDetailRead)
def get_idol_detail_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> IdolDetailRead:
    result = CacheService.get_cached_idol_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Idol not found")
    return result

# Manager/admin settings pages, also registered before /{id}.
@router.get("/manager-idols-page", response_model=ManagerIdolsPageRead)
def get_manager_idols_page_data(db: Session = Depends(get_db)) -> ManagerIdolsPageRead:
    return CacheService.get_cached_manager_idols_page(db)

@router.get("/manager-idol-form-page", response_model=ManagerIdolFormPageRead)
def get_manager_idol_form_page_data(db: Session = Depends(get_db)) -> ManagerIdolFormPageRead:
    return CacheService.get_cached_manager_idol_form_page(db)

@router.get("/{id}", response_model=IdolRead)
def get_idol_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> Idol:
    idol = IdolService.get_idol(db, id)
    if not idol:
        raise HTTPException(status_code=404, detail="Idol not found")
    return idol

@router.put("/update/{id}", response_model=IdolRead)
def update_existing_idol(id: uuid.UUID, data: IdolUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Idol:
    try:
        result = IdolService.update_idol(db, id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_groups_page()  # group_id may have changed
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_idol_details()  # sibling lists may have changed
    CacheService.delete_cached_group_details()
    return result

@router.delete("/delete/{id}", response_model=MessageResponse)
def delete_existing_idol(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    # Soft delete; see idol_service.delete_idol.
    try:
        IdolService.delete_idol(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_idol_details()
    CacheService.delete_cached_group_details()
    return MessageResponse(msg="Idol deleted successfully")

@router.patch("/activate/{id}", response_model=IdolRead)
def activate_existing_idol(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Idol:
    try:
        result = IdolService.reactivate_idol(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_idol_details()
    CacheService.delete_cached_group_details()
    return result

@router.post("/{id}/image", response_model=IdolRead)
def upload_idol_image(id: uuid.UUID, image: UploadFile = File(...), current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Idol:
    """Replace an idol's profile image only."""
    try:
        image_url = get_storage().save(image, subfolder="idols")
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        result = IdolService.set_idol_image(db, id, image_url, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_members_page()  # embeds profile_image_url
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_idol_details()
    CacheService.delete_cached_group_details()
    return result
