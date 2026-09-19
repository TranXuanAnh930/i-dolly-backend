import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import ip_key, rate_limit
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

# Company-scoped exactly like groups/idols (database-design.md §4): a manager
# may only create/edit/delete concerts for their own company_id; admins are
# unrestricted. venues/idols/groups referenced must exist (concert_service
# validates FKs explicitly since we're not relying on a live DB round-trip
# to surface a clean 404 instead of an IntegrityError).
router = APIRouter(prefix="/concerts", tags=["Concerts"])

@router.post("/add", response_model=ConcertRead)
async def add_new_concert(concert: ConcertCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Concert:
    try:
        result = ConcertService.add_concert(db, concert, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_events_page()
    CacheService.delete_cached_manager_events_page()
    return result

@router.get("/all", response_model=List[ConcertRead])
async def list_concerts(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)) -> list[Concert]:
    result = ConcertService.get_concerts(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concerts found")
    return result

@router.get("/events-page", response_model=EventsPageRead)
async def get_events_page_data(db: Session = Depends(get_db)) -> EventsPageRead:
    result = CacheService.get_cached_events_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concerts found")
    return result

@router.get("/manager-events-page", response_model=ManagerEventsPageRead)
async def get_manager_events_page_data(db: Session = Depends(get_db)) -> ManagerEventsPageRead:
    return CacheService.get_cached_manager_events_page(db)

@router.get("/{id}/detail", response_model=ConcertDetailRead)
async def get_concert_detail_by_id(id: uuid.UUID, current_user: Users | None = Depends(get_current_user_optional), db: Session = Depends(get_db)) -> ConcertDetailRead:
    # The cached part (concert/venue/ticket_types/lineup/campaigns) is identical for every
    # viewer, guest or fan. has_ticket/has_won_lottery/entered_campaign_ids/
    # my_lottery_preferences are always computed fresh, never cached — merging a logged-in
    # fan's own state onto a cache hit is safe; caching it would leak one fan's state to
    # whoever's request happens to hit the same cache entry next.
    result = CacheService.get_cached_concert_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Concert not found")
    if current_user:
        campaign_ids = [campaign.id for campaign in result.lottery_campaigns]
        personalization = ConcertService.get_personalization(db, id, current_user, campaign_ids)
        result = result.model_copy(update=personalization)
    return result

@router.get("/{id}", response_model=ConcertRead)
async def get_concert_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> Concert:
    concert = ConcertService.get_concert(db, id)
    if not concert:
        raise HTTPException(status_code=404, detail="Concert not found")
    return concert

@router.put("/update/{id}", response_model=ConcertRead)
async def update_existing_concert(id: uuid.UUID, data: ConcertUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> Concert:
    try:
        result = ConcertService.update_concert(db, id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_events_page()
    CacheService.delete_cached_manager_events_page()
    CacheService.delete_cached_concert_detail(id)
    return result

@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_concert(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    # Cancels (sets status="cancelled") rather than deleting the row — see
    # concert_service.delete_concert. Kept on DELETE /delete/{id} for URL
    # stability with existing clients; a manager can move the status off
    # "cancelled" again via PUT /concerts/update/{id} same as any other
    # status change.
    try:
        ConcertService.delete_concert(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_events_page()
    CacheService.delete_cached_manager_events_page()
    CacheService.delete_cached_concert_detail(id)
    return MessageResponse(msg="Concert cancelled successfully")


# --- concert_performers (join table) — nested under /concerts/performers,
# same rationale as idol_positions: no independent identity outside the
# (concert, idol|group) pair it links. Scoped via the parent concert's
# company_id (concert_service._manager_scope_violation).

@router.post("/performers/assign", response_model=ConcertPerformerRead)
async def assign_concert_performer(data: ConcertPerformerAssign, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> ConcertPerformer:
    try:
        result = ConcertService.assign_performer(db, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_concert_detail(data.concert_id)  # lineup/performing_groups changed
    return result

@router.get("/performers/concert/{concert_id}", response_model=List[ConcertPerformerRead])
async def list_concert_performers(concert_id: uuid.UUID, db: Session = Depends(get_db)) -> list[ConcertPerformer]:
    result = ConcertService.get_performers(db, concert_id)
    if not result:
        raise HTTPException(status_code=404, detail="This concert has no performers assigned")
    return result

# Bulk read — lets a client that needs to know which concerts feature a
# given idol/group (e.g. a group's detail page) fetch every performer link
# in one request instead of looping over every concert.
@router.get("/performers/all", response_model=List[ConcertPerformerRead])
async def list_all_concert_performers(db: Session = Depends(get_db)) -> list[ConcertPerformer]:
    result = ConcertService.get_all_performers(db)
    if not result:
        raise HTTPException(status_code=404, detail="No concert performers found")
    return result

@router.delete("/performers/{id}", response_model=MessageResponse)
async def unassign_concert_performer(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        result = ConcertService.remove_performer(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_concert_detail(result.concert_id)
    return MessageResponse(msg="Performer unassigned from concert successfully")


@router.put("/lottery-draw/{id}", response_model=MessageResponse)
async def draw_lottery_for_concert(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> MessageResponse:
    # Company-scoping has to happen HERE, synchronously, not inside the
    # Celery task — draw_lottery's own _user_scope_violation check runs in
    # the worker process, with no way to turn a rejection back into an HTTP
    # response for a caller who's already gotten back "scheduled". Without
    # this, a manager from a different company got a 200 for a task that
    # silently no-oped in the worker (caught by
    # test_permissions.py::test_draw_lottery_cross_company_manager_forbidden).
    concert = ConcertService.get_concert(db, id)
    if not concert:
        raise HTTPException(status_code=404, detail="Concert not found")
    if ConcertService._manager_scope_violation(current_user, concert.company_id):
        raise HTTPException(status_code=403, detail="Managers can only manage concerts for their own company")

    # Fire-and-forget from here on: the actual draw (LotteryResult) runs
    # async in a Celery worker — see app/tasks/lottery.py /
    # lottery_draw_service.draw_lottery. This response is just a queued
    # acknowledgement, so it can't declare response_model=LotteryResult
    # without failing validation on every call.
    celery_app.send_task("app.tasks.lottery.draw_lottery", args=[str(id), str(current_user.id)])
    return MessageResponse(msg="Lottery draw task has been scheduled. Results will be available once the task is complete.")