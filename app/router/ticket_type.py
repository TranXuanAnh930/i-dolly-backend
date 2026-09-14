import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models.user import Users
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.db_triggers import TriggerViolationError
from app.schema.ticket_type import TicketTypeCreate, TicketTypeRead, TicketTypeUpdate
from app.services.ticket_type_service import (
    add_ticket_type,
    delete_ticket_type,
    get_ticket_type,
    get_ticket_types,
    update_ticket_type,
)

# Company-scoped via the parent concert (ticket_type_service). Nested under
# /ticket_types rather than under /concerts since it's addressed by its own
# id elsewhere (lottery_preferences/lottery_campaigns/tickets all reference
# ticket_type_id directly).
router = APIRouter(prefix="/ticket_types", tags=["Ticket Types"])

def _raise_for(result, not_found_detail: str):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage ticket types for their own company's concerts")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "invalid":
        raise HTTPException(status_code=400, detail="total_quantity cannot be less than sold_quantity")
    if result == "price_locked":
        raise HTTPException(status_code=403, detail="Managers cannot change ticket price after creation — ask an admin")
    if result == "capacity_locked":
        raise HTTPException(status_code=403, detail="Concert is already on sale — cancel it first, then resize ticket capacity once it's cancelled")

@router.post("/add", response_model=TicketTypeRead)
async def add_new_ticket_type(data: TicketTypeCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    try:
        result = add_ticket_type(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    if isinstance(result, str):
        _raise_for(result, "Concert not found")
    return result

@router.get("/concert/{concert_id}", response_model=List[TicketTypeRead])
async def list_ticket_types(concert_id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_ticket_types(db, concert_id)
    if not result:
        raise HTTPException(status_code=404, detail="No ticket types found for this concert")
    return result

@router.get("/{id}", response_model=TicketTypeRead)
async def get_ticket_type_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    ticket_type = get_ticket_type(db, id)
    if not ticket_type:
        raise HTTPException(status_code=404, detail="Ticket type not found")
    return ticket_type

@router.put("/update/{id}", response_model=TicketTypeRead)
async def update_existing_ticket_type(id: uuid.UUID, data: TicketTypeUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    try:
        result = update_ticket_type(db, id, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    if isinstance(result, str):
        _raise_for(result, "Ticket type not found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_ticket_type(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = delete_ticket_type(db, id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Ticket type not found")
    return {"msg": "Ticket type deleted successfully"}
