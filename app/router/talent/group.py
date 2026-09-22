import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.db.models.talent import Group
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.talent import (
    GroupCreate,
    GroupDetailRead,
    GroupRead,
    GroupsPageRead,
    GroupUpdate,
    ManagerGroupsPageRead,
)
from app.services.talent.group_service import GroupService

# require_manager_or_admin per database-design.md §4's role table ("CRUD own
# company's idols/groups"). Company-scoped: a manager may only create/edit/
# delete a group whose company_id matches their own current_user.company_id
# (group_service._manager_scope_violation) — admins are unrestricted. This
# was the previously-flagged gap (CLAUDE.md §5 item 8 / database-design.md
# §7.2); now closed for groups/idols.
router = APIRouter(prefix="/groups", tags=["Groups"])

@router.post("/add", response_model=GroupRead)
async def add_new_group(group: GroupCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Group:
    try:
        result = GroupService.add_group(db, group, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_members_page()  # the group filter dropdown on the members page just gained an entry
    CacheService.delete_cached_manager_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    return result

# FRONTEND: not currently called by i-dolly-frontend — the idols store that
# called it was deleted. Group lists come from /groups/groups-page,
# /groups/manager-groups-page, or embedded in the store/members bundles
# (StorePageRead.groups, MembersPageRead).
@router.get("/all", response_model=List[GroupRead])
async def list_groups(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[Group]:
    result = GroupService.get_groups(db)
    if not result:
        raise HTTPException(status_code=404, detail="No groups found")
    return result

@router.get("/groups-page", response_model=GroupsPageRead)
async def get_groups_page_data(db: Session = Depends(get_db)) -> GroupsPageRead:
    result = CacheService.get_cached_groups_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No groups found")
    return result

@router.get("/manager-groups-page", response_model=ManagerGroupsPageRead)
async def get_manager_groups_page_data(db: Session = Depends(get_db)) -> ManagerGroupsPageRead:
    return CacheService.get_cached_manager_groups_page(db)

@router.get("/{id}/detail", response_model=GroupDetailRead)
async def get_group_detail_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> GroupDetailRead:
    result = CacheService.get_cached_group_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Group not found")
    return result

@router.get("/{id}", response_model=GroupRead)
async def get_group_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> Group:
    group = GroupService.get_group(db, id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group

@router.put("/update/{id}", response_model=GroupRead)
async def update_existing_group(id: uuid.UUID, data: GroupUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Group:
    try:
        result = GroupService.update_group(db, id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_manager_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_group_details()  # this group's own detail page changed
    CacheService.delete_cached_idol_details()  # ...and so did every member's embedded copy of it
    return result

@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_group(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    # Soft delete (sets is_active=False) — see group_service.delete_group.
    try:
        GroupService.delete_group(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_manager_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_group_details()
    CacheService.delete_cached_idol_details()
    return MessageResponse(msg="Group deleted successfully")

@router.patch("/activate/{id}", response_model=GroupRead)
async def activate_existing_group(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Group:
    try:
        result = GroupService.reactivate_group(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_manager_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_group_details()
    CacheService.delete_cached_idol_details()
    return result
