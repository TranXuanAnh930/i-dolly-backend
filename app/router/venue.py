from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.cache.rate_limit import ip_key, rate_limit
from app.deps.auth import require_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.venue import VenueCreate, VenueUpdate, VenueRead
from app.services.venue_service import add_venue, get_venues, get_venue, update_venue, delete_venue

# Admin-only, like management_companies/categories: a venue is shared,
# platform-level data, not owned by one company (database-design.md §3.7).
router = APIRouter(prefix="/venues", tags=["Venues"])

@router.post("/add", response_model=VenueRead)
async def add_new_venue(venue: VenueCreate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    return add_venue(db, venue)

@router.get("/all", response_model=List[VenueRead])
async def list_venues(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)):
    result = get_venues(db)
    if not result:
        raise HTTPException(status_code=404, detail="No venues found")
    return result

@router.get("/{id}", response_model=VenueRead)
async def get_venue_by_id(id: int, db: Session = Depends(get_db)):
    venue = get_venue(db, id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue

@router.put("/update/{id}", response_model=VenueRead)
async def update_existing_venue(id: int, data: VenueUpdate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    db_venue = update_venue(db, id, data)
    if not db_venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    return db_venue

@router.delete("/delete/{id}")
async def delete_existing_venue(id: int, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    result = delete_venue(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Venue not found")
    return {"msg": "Venue deleted successfully"}
