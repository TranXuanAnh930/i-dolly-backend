import uuid
from datetime import date
from typing import Any, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.db.models.talent import Idol
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
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

# Same company-scoping as groups.py — see the comment there. add_idol/
# update_idol also carry the pre-existing group/company cross-field check
# (§3.4), so a mutating call can now fail for three distinct reasons:
# ForbiddenError (403, manager wrong company), NotFoundError (404), or
# BadRequestError (400, group_id belongs to a different company, or is
# deactivated).
router = APIRouter(prefix="/idols", tags=["Idols"])

# multipart/form-data, not JSON — this is the file-upload requirement
# (an optional `image` file alongside the rest of the profile in the same
# request). FastAPI can't mix a JSON body with Form/File fields on one
# endpoint, so this replaced the previous plain-JSON version; any client
# posting here now sends form fields, not a JSON body.
@router.post("/add", response_model=IdolRead)
async def add_new_idol(
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
            profile_image_url = await get_storage().save(image, subfolder="idols")
        except StorageError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    idol = IdolCreate(
        name=name, company_id=company_id, group_id=group_id, date_of_birth=date_of_birth,
        hometown=hometown, color_id=color_id, short_intro=short_intro,
        long_description=long_description, profile_image_url=profile_image_url,
    )
    try:
        return IdolService.add_idol(db, idol, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.get("/all", response_model=List[IdolRead])
async def list_idols(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[Idol]:
    result = IdolService.get_idols(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idols found")
    return result

# Page-shaped reads — registered before /{id} so the literal "members-page"
# segment isn't swallowed by the {id}: uuid.UUID route.
@router.get("/members-page", response_model=MembersPageRead)
async def get_members_page_data(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = IdolService.get_members_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idols found")
    return result

@router.get("/{id}/detail", response_model=IdolDetailRead)
async def get_idol_detail_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = IdolService.get_idol_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Idol not found")
    return result

# Manager/admin settings pages — ManagerIdolsPage only needs idols+groups
# (no colors); ManagerIdolFormPage needs all three for its dropdowns. Both
# registered before /{id} for the same reason as the routes above.
@router.get("/manager-idols-page", response_model=ManagerIdolsPageRead)
async def get_manager_idols_page_data(db: Session = Depends(get_db)) -> dict[str, Any]:
    return IdolService.get_manager_idols_page(db)

@router.get("/manager-idol-form-page", response_model=ManagerIdolFormPageRead)
async def get_manager_idol_form_page_data(db: Session = Depends(get_db)) -> dict[str, Any]:
    return IdolService.get_manager_idol_form_page(db)

@router.get("/{id}", response_model=IdolRead)
async def get_idol_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> Idol:
    idol = IdolService.get_idol(db, id)
    if not idol:
        raise HTTPException(status_code=404, detail="Idol not found")
    return idol

@router.put("/update/{id}", response_model=IdolRead)
async def update_existing_idol(id: uuid.UUID, data: IdolUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Idol:
    try:
        return IdolService.update_idol(db, id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.delete("/delete/{id}")
async def delete_existing_idol(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> dict[str, str]:
    # Soft delete (sets is_active=False) — see idol_service.delete_idol.
    try:
        IdolService.delete_idol(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return {"msg": "Idol deleted successfully"}

@router.patch("/activate/{id}", response_model=IdolRead)
async def activate_existing_idol(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Idol:
    try:
        return IdolService.reactivate_idol(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.post("/{id}/image", response_model=IdolRead)
async def upload_idol_image(id: uuid.UUID, image: UploadFile = File(...), current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Idol:
    """Replace an existing idol's photo without touching any other field —
    the complement to the inline upload on /idols/add."""
    try:
        image_url = await get_storage().save(image, subfolder="idols")
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        return IdolService.set_idol_image(db, id, image_url, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
