import uuid
from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.cache.rate_limit import ip_key, rate_limit
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.group import GroupCreate, GroupUpdate, GroupRead, GroupsPageRead, GroupDetailRead
from app.services.group_service import (
    add_group, get_groups, get_group, update_group, delete_group,
    get_groups_page, get_group_detail,
)

# require_manager_or_admin per database-design.md §4's role table ("CRUD own
# company's idols/groups"). Company-scoped: a manager may only create/edit/
# delete a group whose company_id matches their own current_user.company_id
# (group_service._manager_scope_violation) — admins are unrestricted. This
# was the previously-flagged gap (CLAUDE.md §5 item 8 / database-design.md
# §7.2); now closed for groups/idols.
router = APIRouter(prefix="/groups", tags=["Groups"])

def _raise_for(result, not_found_detail: str):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage groups for their own company")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)

@router.post("/add", response_model=GroupRead)
async def add_new_group(group: GroupCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = add_group(db, group, current_user)
    if isinstance(result, str):
        _raise_for(result, "Management company not found")
    return result

@router.get("/all", response_model=List[GroupRead])
async def list_groups(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)):
    result = get_groups(db)
    if not result:
        raise HTTPException(status_code=404, detail="No groups found")
    return result

@router.get("/groups-page", response_model=GroupsPageRead)
async def get_groups_page_data(db: Session = Depends(get_db)):
    result = get_groups_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No groups found")
    return result

@router.get("/{id}/detail", response_model=GroupDetailRead)
async def get_group_detail_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_group_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Group not found")
    return result

@router.get("/{id}", response_model=GroupRead)
async def get_group_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    group = get_group(db, id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group

@router.put("/update/{id}", response_model=GroupRead)
async def update_existing_group(id: uuid.UUID, data: GroupUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = update_group(db, id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Group not found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_group(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = delete_group(db, id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Group not found")
    return {"msg": "Group deleted successfully"}
