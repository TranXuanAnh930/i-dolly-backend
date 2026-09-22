import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import TicketType
from app.db.models.identity import Users
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.exception.db_triggers import TriggerViolationError
from app.schema.common import MessageResponse
from app.schema.events import TicketTypeCreate, TicketTypeRead, TicketTypeUpdate
from app.services.events.ticket_type_service import TicketTypeService

# Company-scoped via the parent concert (ticket_type_service). Nested under
# /ticket_types rather than under /concerts since it's addressed by its own
# id elsewhere (lottery_preferences/lottery_campaigns/tickets all reference
# ticket_type_id directly).
router = APIRouter(prefix="/ticket_types", tags=["Ticket Types"])

@router.post("/add", response_model=TicketTypeRead)
async def add_new_ticket_type(data: TicketTypeCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> TicketType:
    try:
        result = TicketTypeService.add_ticket_type(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_concert_detail(data.concert_id)  # its parent concert's ticket_types list just grew
    return result

@router.get("/concert/{concert_id}", response_model=List[TicketTypeRead])
async def list_ticket_types(concert_id: uuid.UUID, db: Session = Depends(get_db)) -> list[TicketType]:
    result = TicketTypeService.get_ticket_types(db, concert_id)
    if not result:
        raise HTTPException(status_code=404, detail="No ticket types found for this concert")
    return result

# FRONTEND: not currently called by i-dolly-frontend — a tier's fields reach
# the UI embedded in GET /concerts/{id}/detail (ticket_types[]), so nothing
# needs to resolve a bare ticket_type_id on its own any more.
@router.get("/{id}", response_model=TicketTypeRead)
async def get_ticket_type_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> TicketType:
    ticket_type = TicketTypeService.get_ticket_type(db, id)
    if not ticket_type:
        raise HTTPException(status_code=404, detail="Ticket type not found")
    return ticket_type

# FRONTEND: not currently called by i-dolly-frontend. A manager can create a
# ticket tier (TicketTypesService.create -> POST /add) but has no UI to edit
# or delete one afterward.
@router.put("/update/{id}", response_model=TicketTypeRead)
async def update_existing_ticket_type(id: uuid.UUID, data: TicketTypeUpdate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> TicketType:
    try:
        result = TicketTypeService.update_ticket_type(db, id, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_concert_detail(result.concert_id)
    return result

# FRONTEND: not currently called by i-dolly-frontend.
@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_ticket_type(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        result = TicketTypeService.delete_ticket_type(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_concert_detail(result.concert_id)
    return MessageResponse(msg="Ticket type deleted successfully")
