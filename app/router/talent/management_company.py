import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.db.models.talent import ManagementCompany
from app.deps.auth import require_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.talent import ManagementCompanyBase, ManagementCompanyCreate, ManagementCompanyRead
from app.services.talent.management_company_service import ManagementCompanyService

# Company management stays admin-only (unlike groups/idols, which a manager
# CRUDs for their own company): a manager account is scoped BY a company_id,
# so creating/editing the company record itself is a platform-level action,
# not something a manager does for themselves (database-design.md §4).
router = APIRouter(prefix="/management_companies", tags=["Management Companies"])

@router.post("/add", response_model=ManagementCompanyRead)
async def add_new_company(company: ManagementCompanyCreate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> ManagementCompany:
    db_company = ManagementCompanyService.add_company(db, company)
    CacheService.delete_cached_management_companies()
    return db_company

@router.get("/all", response_model=List[ManagementCompanyRead])
async def list_companies(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[ManagementCompany]:
    result = CacheService.get_cached_management_companies(db)
    if not result:
        raise HTTPException(status_code=404, detail="No management companies found")
    return result

# FRONTEND: not currently called by i-dolly-frontend. CompaniesService only
# ever calls the inherited getAllPublic() (GET /management_companies/all) —
# there's no single-company lookup anywhere in the UI.
@router.get("/{id}", response_model=ManagementCompanyRead)
async def get_company_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> ManagementCompany:
    company = ManagementCompanyService.get_company(db, id)
    if not company:
        raise HTTPException(status_code=404, detail="Management company not found")
    return company

@router.put("/update/{id}", response_model=ManagementCompanyRead)
async def update_existing_company(id: uuid.UUID, data: ManagementCompanyBase, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> ManagementCompany:
    try:
        db_company = ManagementCompanyService.update_company(db, id, data)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_management_companies()
    return db_company

@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_company(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> MessageResponse:
    result = ManagementCompanyService.delete_company(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Management company not found")
    CacheService.delete_cached_management_companies()
    return MessageResponse(msg="Management company deleted successfully")
