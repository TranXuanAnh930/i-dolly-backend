import uuid
from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.cache.rate_limit import ip_key, rate_limit
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.concert import (
    ConcertCreate, ConcertUpdate, ConcertRead, ConcertPerformerAssign, ConcertPerformerRead,
    EventsPageRead, ConcertDetailRead, ManagerEventsPageRead,
)
from app.services.concert_service import (
    add_concert, get_concerts, get_concert, update_concert, delete_concert,
    assign_performer, get_performers, get_all_performers, remove_performer,
    get_events_page, get_concert_detail, get_manager_events_page,
)

# Company-scoped exactly like groups/idols (database-design.md §4): a manager
# may only create/edit/delete concerts for their own company_id; admins are
# unrestricted. venues/idols/groups referenced must exist (concert_service
# validates FKs explicitly since we're not relying on a live DB round-trip
# to surface a clean 404 instead of an IntegrityError).
router = APIRouter(prefix="/concerts", tags=["Concerts"])

def _raise_for(result, not_found_detail: str):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage concerts for their own company")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "invalid":
        raise HTTPException(status_code=400, detail="Exactly one of idol_id or group_id must be set")
    if result == "event_locked":
        raise HTTPException(status_code=403, detail="Concert is already on sale — cancel it first, then edit the date/doors-open time once it's cancelled")

@router.post("/add", response_model=ConcertRead)
async def add_new_concert(concert: ConcertCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = add_concert(db, concert, current_user)
    if isinstance(result, str):
        _raise_for(result, "Management company or venue not found")
    return result

@router.get("/all", response_model=List[ConcertRead])
async def list_concerts(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)):
    result = get_concerts(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concerts found")
    return result

@router.get("/events-page", response_model=EventsPageRead)
async def get_events_page_data(db: Session = Depends(get_db)):
    result = get_events_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concerts found")
    return result

@router.get("/manager-events-page", response_model=ManagerEventsPageRead)
async def get_manager_events_page_data(db: Session = Depends(get_db)):
    return get_manager_events_page(db)

@router.get("/{id}/detail", response_model=ConcertDetailRead)
async def get_concert_detail_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_concert_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Concert not found")
    return result

@router.get("/{id}", response_model=ConcertRead)
async def get_concert_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    concert = get_concert(db, id)
    if not concert:
        raise HTTPException(status_code=404, detail="Concert not found")
    return concert

@router.put("/update/{id}", response_model=ConcertRead)
async def update_existing_concert(id: uuid.UUID, data: ConcertUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = update_concert(db, id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Concert or venue not found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_concert(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    # Cancels (sets status="cancelled") rather than deleting the row — see
    # concert_service.delete_concert. Kept on DELETE /delete/{id} for URL
    # stability with existing clients; a manager can move the status off
    # "cancelled" again via PUT /concerts/update/{id} same as any other
    # status change.
    result = delete_concert(db, id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Concert not found")
    return {"msg": "Concert cancelled successfully"}


# --- concert_performers (join table) — nested under /concerts/performers,
# same rationale as idol_positions: no independent identity outside the
# (concert, idol|group) pair it links. Scoped via the parent concert's
# company_id (concert_service._manager_scope_violation).

@router.post("/performers/assign", response_model=ConcertPerformerRead)
async def assign_concert_performer(data: ConcertPerformerAssign, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = assign_performer(db, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Concert, idol, or group not found")
    return result

@router.get("/performers/concert/{concert_id}", response_model=List[ConcertPerformerRead])
async def list_concert_performers(concert_id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_performers(db, concert_id)
    if not result:
        raise HTTPException(status_code=404, detail="This concert has no performers assigned")
    return result

# Bulk read — lets a client that needs to know which concerts feature a
# given idol/group (e.g. a group's detail page) fetch every performer link
# in one request instead of looping over every concert.
@router.get("/performers/all", response_model=List[ConcertPerformerRead])
async def list_all_concert_performers(db: Session = Depends(get_db)):
    result = get_all_performers(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concert performers found")
    return result

@router.delete("/performers/{id}")
async def unassign_concert_performer(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = remove_performer(db, id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Performer assignment not found")
    return {"msg": "Performer unassigned from concert successfully"}
