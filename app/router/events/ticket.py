import uuid
from typing import List

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
from app.schema.identity import UserRole
from app.services.events.ticket_service import TicketService

# Fans buy direct-sale tickets via /checkout, pay for lottery wins via /{id}/checkout, and read
# their own tickets. add/update/delete are admin-only manual overrides.
router = APIRouter(prefix="/tickets", tags=["Tickets"])

@router.post("/checkout", response_model=TicketRead)
def checkout_new_ticket(data: TicketCheckoutCreate, user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> Ticket:
    try:
        return TicketService.checkout_ticket(db, user.id, data)
    # Specific errors first: several subclass CartItemError, which is caught later as a 404.
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
def checkout_won_lottery_ticket(ticket_id: uuid.UUID, data: WonTicketCheckoutCreate, user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> Ticket:
    try:
        return TicketService.checkout_won_ticket(db, user.id, ticket_id, data)
    # Specific errors first, as in checkout_new_ticket.
    except TicketNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (TicketNotPayableError, PaymentAmountMismatch, UnsupportedGatewayError) as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except TriggerViolationError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.post("/add", response_model=TicketRead)
def add_new_ticket(data: TicketCreate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> Ticket:
    try:
        return TicketService.add_ticket(db, data)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.get("/mine", response_model=List[TicketRead])
def list_my_tickets(current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Ticket]:
    result = TicketService.get_my_tickets(db, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no tickets")
    return result

@router.get("/concert/{concert_id}/sales", response_model=TicketSalesPageRead)
def get_concert_sales(
    concert_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    current_user: Users = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
) -> TicketSalesPageRead:
    try:
        return TicketService.get_concert_ticket_sales(db, concert_id, current_user, page, limit)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.get("/{id}", response_model=TicketRead)
def get_ticket_by_id(id: uuid.UUID, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)) -> Ticket:
    ticket = TicketService.get_ticket(db, id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role not in (UserRole.admin, UserRole.manager) and ticket.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view your own tickets")
    return ticket

# Not used by the frontend.
@router.put("/update/{id}", response_model=TicketRead)
def update_existing_ticket(id: uuid.UUID, data: TicketUpdate, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> Ticket:
    try:
        return TicketService.update_ticket(db, id, data)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.delete("/delete/{id}", response_model=MessageResponse)
def delete_existing_ticket(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        TicketService.delete_ticket(db, id)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return MessageResponse(msg="Ticket deleted successfully")
