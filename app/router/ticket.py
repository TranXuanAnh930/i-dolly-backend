import uuid
from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.deps.auth import get_current_user, require_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.ticket import TicketCreate, TicketUpdate, TicketRead
from app.services.ticket_service import add_ticket, get_my_tickets, get_ticket, update_ticket, delete_ticket
from app.exception.db_triggers import TriggerViolationError

# ADMIN-ONLY create/update/delete — explicit stopgap until the real
# checkout/draw-job flow exists (see TicketCreate's docstring and
# database-design.md §7.4). Fans can only read their own tickets.
router = APIRouter(prefix="/tickets", tags=["Tickets"])

def _raise_for(result, not_found_detail: str):
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "conflict":
        raise HTTPException(status_code=400, detail="This user already holds a live ticket for this concert")

@router.post("/add", response_model=TicketRead)
async def add_new_ticket(data: TicketCreate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        result = add_ticket(db, data)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    if isinstance(result, str):
        _raise_for(result, "Ticket type, user, or lottery entry not found")
    return result

@router.get("/mine", response_model=List[TicketRead])
async def list_my_tickets(current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    result = get_my_tickets(db, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no tickets")
    return result

@router.get("/{id}", response_model=TicketRead)
async def get_ticket_by_id(id: uuid.UUID, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = get_ticket(db, id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role not in ("admin", "manager") and ticket.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view your own tickets")
    return ticket

@router.put("/update/{id}", response_model=TicketRead)
async def update_existing_ticket(id: uuid.UUID, data: TicketUpdate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    result = update_ticket(db, id, data)
    if isinstance(result, str):
        _raise_for(result, "Ticket not found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_ticket(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    result = delete_ticket(db, id)
    if isinstance(result, str):
        _raise_for(result, "Ticket not found")
    return {"msg": "Ticket deleted successfully"}
