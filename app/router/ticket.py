import uuid
from fastapi import HTTPException, Depends, APIRouter, Query
from typing import List
from sqlalchemy.orm import Session
from app.cache.rate_limit import user_key, rate_limit
from app.deps.auth import get_current_user, require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.ticket import TicketCreate, TicketUpdate, TicketRead, TicketCheckoutCreate, TicketSalesPageRead
from app.services.ticket_service import (
    add_ticket, checkout_ticket, get_my_tickets, get_ticket, update_ticket, delete_ticket,
    get_concert_ticket_sales,
)
from app.exception.checkout import (
    CartItemError,
    InsufficientTicketStockError,
    PaymentAmountMismatch,
    UnsupportedGatewayError,
    TicketTypeNotFoundError,
)
from app.exception.db_triggers import TriggerViolationError

# add/update/delete below stay the ADMIN-ONLY stopgap until the lottery
# draw job exists (see TicketCreate's docstring and database-design.md
# §7.4). Fans buy direct-sale tickets through /checkout, and can only read
# their own tickets otherwise.
router = APIRouter(prefix="/tickets", tags=["Tickets"])

def _raise_for(result, not_found_detail: str):
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "conflict":
        raise HTTPException(status_code=400, detail="This user already holds a live ticket for this concert")
    if result == "fan_only":
        raise HTTPException(status_code=403, detail="Tickets can only be issued to fan accounts")

@router.post("/checkout", response_model=TicketRead)
async def checkout_new_ticket(data: TicketCheckoutCreate, user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)):
    try:
        return checkout_ticket(db, user.id, data)
    # Order matters here — InsufficientTicketStockError, PaymentAmountMismatch
    # and UnsupportedGatewayError all subclass CartItemError, so the generic
    # catch must come last or it swallows every more specific case as a 404,
    # same reasoning as order.py's checkout_order.
    except (InsufficientTicketStockError, PaymentAmountMismatch, UnsupportedGatewayError) as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except TicketTypeNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except CartItemError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except TriggerViolationError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=str(e))

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

@router.get("/concert/{concert_id}/sales", response_model=TicketSalesPageRead)
async def get_concert_sales(
    concert_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    current_user: Users = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
):
    result = get_concert_ticket_sales(db, concert_id, current_user, page, limit)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Concert not found")
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only view ticket sales for their own company's concerts")
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
