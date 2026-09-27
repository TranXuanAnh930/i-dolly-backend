import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import ip_key, rate_limit, user_or_ip_key
from app.celery_app import celery_app
from app.db.models.events import Concert, ConcertPerformer
from app.db.models.identity import Users
from app.deps.auth import get_current_user_optional, require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.events import (
    ConcertCreate,
    ConcertDetailRead,
    ConcertPerformerAssign,
    ConcertPerformerRead,
    ConcertRead,
    ConcertUpdate,
    EventsPageRead,
    ManagerEventsPageRead,
)
from app.services.events.concert_service import ConcertService

# Managers can only create/edit/delete their own company's concerts; admins are unrestricted.
router = APIRouter(prefix="/concerts", tags=["Concerts"])

@router.post("/add", response_model=ConcertRead)
def add_new_concert(concert: ConcertCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Concert:
    try:
        result = ConcertService.add_concert(db, concert, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_events_page()
    CacheService.delete_cached_manager_events_page()
    return result

# Not used by the frontend.
@router.get("/all", response_model=List[ConcertRead])
def list_concerts(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[Concert]:
    result = ConcertService.get_concerts(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concerts found")
    return result

@router.get("/events-page", response_model=EventsPageRead)
def get_events_page_data(db: Session = Depends(get_db)) -> EventsPageRead:
    result = CacheService.get_cached_events_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concerts found")
    return result

@router.get("/manager-events-page", response_model=ManagerEventsPageRead)
def get_manager_events_page_data(db: Session = Depends(get_db)) -> ManagerEventsPageRead:
    return CacheService.get_cached_manager_events_page(db)

@router.get("/{id}/detail", response_model=ConcertDetailRead)
def get_concert_detail_by_id(id: uuid.UUID, current_user: Users | None = Depends(get_current_user_optional), _: None = Depends(rate_limit(30, 60, user_or_ip_key)), db: Session = Depends(get_db)) -> ConcertDetailRead:
    # The cached part is identical for every viewer; per-viewer fields are computed fresh each
    # request so one fan's state is never cached and served to another.
    result = CacheService.get_cached_concert_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Concert not found")
    if current_user:
        campaign_ids = [campaign.id for campaign in result.lottery_campaigns]
        personalization = ConcertService.get_personalization(db, id, current_user, campaign_ids)
        result = result.model_copy(update=personalization)
    return result

@router.get("/{id}", response_model=ConcertRead)
def get_concert_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> Concert:
    concert = ConcertService.get_concert(db, id)
    if not concert:
        raise HTTPException(status_code=404, detail="Concert not found")
    return concert

@router.put("/update/{id}", response_model=ConcertRead)
def update_existing_concert(id: uuid.UUID, data: ConcertUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Concert:
    try:
        result = ConcertService.update_concert(db, id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_events_page()
    CacheService.delete_cached_manager_events_page()
    CacheService.delete_cached_concert_detail(id)
    return result

@router.delete("/delete/{id}", response_model=MessageResponse)
def delete_existing_concert(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    # Cancels the concert (status="cancelled") instead of deleting it; see delete_concert.
    try:
        ConcertService.delete_concert(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_events_page()
    CacheService.delete_cached_manager_events_page()
    CacheService.delete_cached_concert_detail(id)
    return MessageResponse(msg="Concert cancelled successfully")


# --- concert_performers (join table), scoped via the parent concert's company.

# Not used by the frontend.
@router.post("/performers/assign", response_model=ConcertPerformerRead)
def assign_concert_performer(data: ConcertPerformerAssign, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> ConcertPerformer:
    try:
        result = ConcertService.assign_performer(db, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_concert_detail(data.concert_id)
    return result

# Not used by the frontend.
@router.get("/performers/concert/{concert_id}", response_model=List[ConcertPerformerRead])
def list_concert_performers(concert_id: uuid.UUID, db: Session = Depends(get_db)) -> list[ConcertPerformer]:
    result = ConcertService.get_performers(db, concert_id)
    if not result:
        raise HTTPException(status_code=404, detail="This concert has no performers assigned")
    return result

# Every performer link across all concerts, in one request.
# Not used by the frontend.
@router.get("/performers/all", response_model=List[ConcertPerformerRead])
def list_all_concert_performers(db: Session = Depends(get_db)) -> list[ConcertPerformer]:
    result = ConcertService.get_all_performers(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concert performers found")
    return result

# Not used by the frontend.
@router.delete("/performers/{id}", response_model=MessageResponse)
def unassign_concert_performer(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        result = ConcertService.remove_performer(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_concert_detail(result.concert_id)
    return MessageResponse(msg="Performer unassigned from concert successfully")


@router.put("/lottery-draw/{id}", response_model=MessageResponse)
def draw_lottery_for_concert(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    # Company scoping is checked here, synchronously: a rejection inside the Celery task couldn't
    # be returned to the caller.
    concert = ConcertService.get_concert(db, id)
    if not concert:
        raise HTTPException(status_code=404, detail="Concert not found")
    if ConcertService._manager_scope_violation(current_user, concert.company_id):
        raise HTTPException(status_code=403, detail="Managers can only manage concerts for their own company")

    # Notify the company's managers now; the draw itself runs later in Celery.
    ConcertService.notify_managers_of_draw_trigger(db, concert)

    # The draw runs in a Celery worker (app/tasks/lottery.py); this only acknowledges the request.
    celery_app.send_task("app.tasks.lottery.draw_lottery", args=[str(id), str(current_user.id)])
    return MessageResponse(msg="Lottery draw task has been scheduled. Results will be available once the task is complete.")