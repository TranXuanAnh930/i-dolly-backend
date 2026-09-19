import uuid
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import Ticket
from app.db.models.identity import Users
from app.deps.auth import get_current_user, require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.exception.checkout import (
    CartItemError,
    InsufficientTicketStockError,
    PaymentAmountMismatch,
    TicketNotFoundError,
    TicketNotPayableError,
    TicketTypeNotFoundError,
    UnsupportedGatewayError,
)
from app.exception.common import ServiceError
from app.exception.db_triggers import TriggerViolationError
from app.schema.common import MessageResponse
from app.schema.events import (
    TicketCheckoutCreate,
    TicketCreate,
    TicketRead,
    TicketSalesPageRead,
    TicketUpdate,
    WonTicketCheckoutCreate,
)
from app.services.events.ticket_service import TicketService

# add/update/delete below stay the ADMIN-ONLY stopgap until the lottery
# draw job exists (see TicketCreate's docstring and database-design.md
# §7.4). Fans buy direct-sale tickets through /checkout, and can only read
# their own tickets otherwise.
router = APIRouter(prefix="/tickets", tags=["Tickets"])

@router.post("/checkout", response_model=TicketRead)
async def checkout_new_ticket(data: TicketCheckoutCreate, user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> Ticket:
    try:
        return TicketService.checkout_ticket(db, user.id, data)
    # Order matters here — InsufficientTicketStockError, PaymentAmountMismatch
    # and UnsupportedGatewayError all subclass CartItemError, so the generic
    # catch must come last or it swallows every more specific case as a 404,
    # same reasoning as order.py's checkout_order.
    except (InsufficientTicketStockError, PaymentAmountMismatch, UnsupportedGatewayError) as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except TicketTypeNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CartItemError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except TriggerViolationError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.post("/{ticket_id}/checkout", response_model=TicketRead)
async def checkout_won_lottery_ticket(ticket_id: uuid.UUID, data: WonTicketCheckoutCreate, user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> Ticket:
    try:
        return TicketService.checkout_won_ticket(db, user.id, ticket_id, data)
    # Same ordering reasoning as checkout_new_ticket above: catch the
    # generic CartItemError-family checks after the more specific ones.
    except TicketNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (TicketNotPayableError, PaymentAmountMismatch, UnsupportedGatewayError) as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except TriggerViolationError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.post("/add", response_model=TicketRead)
async def add_new_ticket(data: TicketCreate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> Ticket:
    try:
        return TicketService.add_ticket(db, data)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.get("/mine", response_model=List[TicketRead])
async def list_my_tickets(current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Ticket]:
    result = TicketService.get_my_tickets(db, current_user)
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
) -> dict[str, Any]:
    try:
        return TicketService.get_concert_ticket_sales(db, concert_id, current_user, page, limit)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.get("/{id}", response_model=TicketRead)
async def get_ticket_by_id(id: uuid.UUID, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)) -> Ticket:
    ticket = TicketService.get_ticket(db, id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role not in ("admin", "manager") and ticket.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view your own tickets")
    return ticket

@router.put("/update/{id}", response_model=TicketRead)
async def update_existing_ticket(id: uuid.UUID, data: TicketUpdate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> Ticket:
    try:
        return TicketService.update_ticket(db, id, data)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_ticket(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        TicketService.delete_ticket(db, id)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return MessageResponse(msg="Ticket deleted successfully")
