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

# Managers can only create/edit/delete their own company's groups; admins are unrestricted.
router = APIRouter(prefix="/groups", tags=["Groups"])

@router.post("/add", response_model=GroupRead)
def add_new_group(group: GroupCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Group:
    try:
        result = GroupService.add_group(db, group, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_members_page()  # embeds the group filter options
    CacheService.delete_cached_manager_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    return result

# Not used by the frontend.
@router.get("/all", response_model=List[GroupRead])
def list_groups(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[Group]:
    result = GroupService.get_groups(db)
    if not result:
        raise HTTPException(status_code=404, detail="No groups found")
    return result

@router.get("/groups-page", response_model=GroupsPageRead)
def get_groups_page_data(db: Session = Depends(get_db)) -> GroupsPageRead:
    result = CacheService.get_cached_groups_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No groups found")
    return result

@router.get("/manager-groups-page", response_model=ManagerGroupsPageRead)
def get_manager_groups_page_data(db: Session = Depends(get_db)) -> ManagerGroupsPageRead:
    return CacheService.get_cached_manager_groups_page(db)

@router.get("/{id}/detail", response_model=GroupDetailRead)
def get_group_detail_by_id(id: uuid.UUID, _: None = Depends(rate_limit(30, 60, ip_key)), db: Session = Depends(get_db)) -> GroupDetailRead:
    result = CacheService.get_cached_group_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Group not found")
    return result

@router.get("/{id}", response_model=GroupRead)
def get_group_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> Group:
    group = GroupService.get_group(db, id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group

@router.put("/update/{id}", response_model=GroupRead)
def update_existing_group(id: uuid.UUID, data: GroupUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Group:
    try:
        result = GroupService.update_group(db, id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_manager_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_group_details()
    CacheService.delete_cached_idol_details()  # idol detail pages embed their group
    return result

@router.delete("/delete/{id}", response_model=MessageResponse)
def delete_existing_group(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    # Soft delete; see group_service.delete_group.
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
def activate_existing_group(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Group:
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
