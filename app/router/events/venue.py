import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.events import Venue
from app.db.models.identity import Users
from app.deps.auth import require_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.events import VenueCreate, VenueRead, VenueUpdate
from app.services.events.venue_service import VenueService

# Admin-only, like management_companies/categories: a venue is shared,
# platform-level data, not owned by one company (database-design.md §3.7).
router = APIRouter(prefix="/venues", tags=["Venues"])

@router.post("/add", response_model=VenueRead)
async def add_new_venue(venue: VenueCreate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> Venue:
    result = VenueService.add_venue(db, venue)
    CacheService.delete_cached_venues()
    return result

@router.get("/all", response_model=List[VenueRead])
async def list_venues(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[Venue]:
    result = CacheService.get_cached_venues(db)
    if not result:
        raise HTTPException(status_code=404, detail="No venues found")
    return result

@router.get("/{id}", response_model=VenueRead)
async def get_venue_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> Venue:
    venue = VenueService.get_venue(db, id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue

@router.put("/update/{id}", response_model=VenueRead)
async def update_existing_venue(id: uuid.UUID, data: VenueUpdate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> Venue:
    try:
        db_venue = VenueService.update_venue(db, id, data)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_venues()
    return db_venue

@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_venue(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> MessageResponse:
    result = VenueService.delete_venue(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Venue not found")
    CacheService.delete_cached_venues()
    return MessageResponse(msg="Venue deleted successfully")
