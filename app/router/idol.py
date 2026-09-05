import uuid
from datetime import date
from fastapi import HTTPException, Depends, APIRouter, Form, File, UploadFile
from typing import List
from sqlalchemy.orm import Session
from app.cache.rate_limit import ip_key, rate_limit
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.idol import IdolCreate, IdolUpdate, IdolRead, MembersPageRead, IdolDetailRead
from app.services.idol_service import (
    add_idol, get_idols, get_idol, update_idol, delete_idol, set_idol_image,
    get_members_page, get_idol_detail,
)
from app.utils.storage import get_storage, StorageError

# Same company-scoping as groups.py — see the comment there. add_idol/
# update_idol also carry the pre-existing group/company cross-field check
# (§3.4), so a mutating call can now fail for three distinct reasons:
# "forbidden" (403, manager wrong company), "not_found" (404), or
# "company_mismatch" (400, group_id belongs to a different company).
router = APIRouter(prefix="/idols", tags=["Idols"])

def _raise_for(result, not_found_detail: str):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage idols for their own company")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "company_mismatch":
        raise HTTPException(status_code=400, detail="group_id belongs to a different company than company_id")

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
):
    profile_image_url = None
    if image is not None:
        try:
            profile_image_url = await get_storage().save(image, subfolder="idols")
        except StorageError as e:
            raise HTTPException(status_code=400, detail=str(e))

    idol = IdolCreate(
        name=name, company_id=company_id, group_id=group_id, date_of_birth=date_of_birth,
        hometown=hometown, color_id=color_id, short_intro=short_intro,
        long_description=long_description, profile_image_url=profile_image_url,
    )
    result = add_idol(db, idol, current_user)
    if isinstance(result, str):
        _raise_for(result, "Management company, group, or idol color not found")
    return result

@router.get("/all", response_model=List[IdolRead])
async def list_idols(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)):
    result = get_idols(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idols found")
    return result

# Page-shaped reads — registered before /{id} so the literal "members-page"
# segment isn't swallowed by the {id}: uuid.UUID route.
@router.get("/members-page", response_model=MembersPageRead)
async def get_members_page_data(db: Session = Depends(get_db)):
    result = get_members_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idols found")
    return result

@router.get("/{id}/detail", response_model=IdolDetailRead)
async def get_idol_detail_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_idol_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Idol not found")
    return result

@router.get("/{id}", response_model=IdolRead)
async def get_idol_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    idol = get_idol(db, id)
    if not idol:
        raise HTTPException(status_code=404, detail="Idol not found")
    return idol

@router.put("/update/{id}", response_model=IdolRead)
async def update_existing_idol(id: uuid.UUID, data: IdolUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = update_idol(db, id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Idol, group, or idol color not found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_idol(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = delete_idol(db, id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Idol not found")
    return {"msg": "Idol deleted successfully"}

@router.post("/{id}/image", response_model=IdolRead)
async def upload_idol_image(id: uuid.UUID, image: UploadFile = File(...), current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    """Replace an existing idol's photo without touching any other field —
    the complement to the inline upload on /idols/add."""
    try:
        image_url = await get_storage().save(image, subfolder="idols")
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = set_idol_image(db, id, image_url, current_user)
    if isinstance(result, str):
        _raise_for(result, "Idol not found")
    return result
