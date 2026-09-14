import uuid

from sqlalchemy.orm import Session

from app.db.models.concert import Concert
from app.db.models.ticket_type import TicketType
from app.db.models.user import Users
from app.exception.db_triggers import commit_or_raise
from app.schema.ticket_type import TicketTypeCreate, TicketTypeUpdate

# Company-scoped via the parent concert's company_id, same pattern as
# concert_performers (concert_service._manager_scope_violation).

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

# Mirrors concert_service._EVENT_OPEN_STATUSES/reasoning: once the parent
# concert is on sale (or further), a ticket type's capacity is frozen for
# managers too — resizing how many tickets are on offer out from under fans
# who already hold entries/tickets is exactly what this blocks. Cancelling
# the concert unlocks it again, same as the concert's own date/capacity.
_EVENT_OPEN_STATUSES = {"on_sale", "sold_out", "completed"}

def add_ticket_type(db: Session, data: TicketTypeCreate, current_user: Users):
    concert = db.get(Concert, data.concert_id)
    if not concert:
        return "not_found"
    if _manager_scope_violation(current_user, concert.company_id):
        return "forbidden"
    db_tt = TicketType(**data.model_dump())
    db.add(db_tt)
    commit_or_raise(db)  # trg_ticket_types_capacity
    db.refresh(db_tt)
    return db_tt

def get_ticket_types(db: Session, concert_id: uuid.UUID):
    result = db.query(TicketType).filter(TicketType.concert_id == concert_id).all()
    if not result:
        return False
    return result

def get_ticket_type(db: Session, id: uuid.UUID):
    return db.get(TicketType, id)

def update_ticket_type(db: Session, id: uuid.UUID, data: TicketTypeUpdate, current_user: Users):
    db_tt = db.get(TicketType, id)
    if not db_tt:
        return "not_found"
    concert = db.get(Concert, db_tt.concert_id)
    if _manager_scope_violation(current_user, concert.company_id):
        return "forbidden"
    if data.total_quantity is not None:
        if (
            current_user.role == "manager"
            and concert.status in _EVENT_OPEN_STATUSES
            and data.total_quantity != db_tt.total_quantity
        ):
            return "capacity_locked"
        if data.total_quantity < db_tt.sold_quantity:
            return "invalid"  # would violate chk_ticket_types_capacity
        db_tt.total_quantity = data.total_quantity
    if data.price is not None:
        # Managers can't reprice a ticket after creation — fans may already
        # hold entries/tickets at the advertised price; only an admin can
        # correct it. Rounded before comparing: price is Numeric(10,2)
        # (Decimal) in the DB but arrives here as a float, and the two
        # don't compare equal bit-for-bit even for the "same" price.
        if current_user.role == "manager" and round(float(db_tt.price), 2) != round(data.price, 2):
            return "price_locked"
        db_tt.price = data.price
    commit_or_raise(db)  # trg_ticket_types_capacity (fires on UPDATE OF total_quantity)
    db.refresh(db_tt)
    return db_tt

def delete_ticket_type(db: Session, id: uuid.UUID, current_user: Users):
    db_tt = db.get(TicketType, id)
    if not db_tt:
        return "not_found"
    concert = db.get(Concert, db_tt.concert_id)
    if _manager_scope_violation(current_user, concert.company_id):
        return "forbidden"
    db.delete(db_tt)
    db.commit()
    return True
