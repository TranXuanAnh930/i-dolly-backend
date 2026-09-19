import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models.events import Concert, TicketType
from app.db.models.identity import Users
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import commit_or_raise
from app.schema.events import TicketTypeCreate, TicketTypeUpdate

# Mirrors concert_service._EVENT_OPEN_STATUSES/reasoning: once the parent
# concert is on sale (or further), a ticket type's capacity is frozen for
# managers too — resizing how many tickets are on offer out from under fans
# who already hold entries/tickets is exactly what this blocks. Cancelling
# the concert unlocks it again, same as the concert's own date/capacity.
_EVENT_OPEN_STATUSES = {"on_sale", "sold_out", "completed"}

class TicketTypeService:

    # Company-scoped via the parent concert's company_id, same pattern as
    # concert_performers (concert_service._manager_scope_violation).

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == "manager" and current_user.company_id != company_id

    @staticmethod
    def add_ticket_type(db: Session, data: TicketTypeCreate, current_user: Users) -> TicketType:
        concert = db.get(Concert, data.concert_id)
        if not concert:
            raise NotFoundError("Concert not found")
        if TicketTypeService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage ticket types for their own company's concerts")
        db_tt = TicketType(**data.model_dump())
        db.add(db_tt)
        commit_or_raise(db)  # trg_ticket_types_capacity
        db.refresh(db_tt)
        return db_tt

    @staticmethod
    def get_ticket_types(db: Session, concert_id: uuid.UUID) -> list[TicketType] | Literal[False]:
        result = db.query(TicketType).filter(TicketType.concert_id == concert_id).all()
        if not result:
            return False
        return result

    @staticmethod
    def get_ticket_type(db: Session, id: uuid.UUID) -> TicketType | None:
        return db.get(TicketType, id)

    @staticmethod
    def update_ticket_type(db: Session, id: uuid.UUID, data: TicketTypeUpdate, current_user: Users) -> TicketType:
        db_tt = db.get(TicketType, id)
        if not db_tt:
            raise NotFoundError("Ticket type not found")
        concert = db.get(Concert, db_tt.concert_id)
        if TicketTypeService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage ticket types for their own company's concerts")
        if data.total_quantity is not None:
            if (
                current_user.role == "manager"
                and concert.status in _EVENT_OPEN_STATUSES
                and data.total_quantity != db_tt.total_quantity
            ):
                raise ForbiddenError("Concert is already on sale — cancel it first, then resize ticket capacity once it's cancelled")
            if data.total_quantity < db_tt.sold_quantity:
                raise BadRequestError("total_quantity cannot be less than sold_quantity")  # would violate chk_ticket_types_capacity
            db_tt.total_quantity = data.total_quantity
        if data.price is not None:
            # Managers can't reprice a ticket after creation — fans may already
            # hold entries/tickets at the advertised price; only an admin can
            # correct it. Rounded before comparing: price is Numeric(10,2)
            # (Decimal) in the DB but arrives here as a float, and the two
            # don't compare equal bit-for-bit even for the "same" price.
            if current_user.role == "manager" and round(float(db_tt.price), 2) != round(data.price, 2):
                raise ForbiddenError("Managers cannot change ticket price after creation — ask an admin")
            db_tt.price = data.price
        commit_or_raise(db)  # trg_ticket_types_capacity (fires on UPDATE OF total_quantity)
        db.refresh(db_tt)
        return db_tt

    @staticmethod
    def delete_ticket_type(db: Session, id: uuid.UUID, current_user: Users) -> TicketType:
        db_tt = db.get(TicketType, id)
        if not db_tt:
            raise NotFoundError("Ticket type not found")
        concert = db.get(Concert, db_tt.concert_id)
        if TicketTypeService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage ticket types for their own company's concerts")
        db.delete(db_tt)
        db.commit()
        return db_tt
