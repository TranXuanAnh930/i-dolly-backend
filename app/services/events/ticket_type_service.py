import uuid

from sqlalchemy.orm import Session

from app.db.models.events import Concert, TicketType
from app.db.models.identity import Users
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import commit_or_raise
from app.schema.events import TicketTypeCreate, TicketTypeUpdate
from app.schema.events.concert import ConcertStatus
from app.schema.identity import UserRole

# While the parent concert is in one of these statuses, a ticket type's capacity can't change
# (same rule as concert_service).
_EVENT_OPEN_STATUSES = {ConcertStatus.on_sale, ConcertStatus.sold_out, ConcertStatus.completed}

class TicketTypeService:

    # Company-scoped via the parent concert's company_id.

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == UserRole.manager and current_user.company_id != company_id

    @staticmethod
    def add_ticket_type(db: Session, data: TicketTypeCreate, current_user: Users) -> TicketType:
        concert = db.get(Concert, data.concert_id)
        if not concert:
            raise NotFoundError("Concert not found")
        if TicketTypeService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage ticket types for their own company's concerts")
        db_tt = TicketType(**data.model_dump())
        db.add(db_tt)
        commit_or_raise(db)
        db.refresh(db_tt)
        return db_tt

    @staticmethod
    def get_ticket_types(db: Session, concert_id: uuid.UUID) -> list[TicketType]:
        return db.query(TicketType).filter(TicketType.concert_id == concert_id).all()

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
                current_user.role == UserRole.manager
                and concert.status in _EVENT_OPEN_STATUSES
                and data.total_quantity != db_tt.total_quantity
            ):
                raise ForbiddenError("Concert is already on sale — cancel it first, then resize ticket capacity once it's cancelled")
            if data.total_quantity < db_tt.sold_quantity:
                raise BadRequestError("total_quantity cannot be less than sold_quantity")
            db_tt.total_quantity = data.total_quantity
        if data.price is not None:
            # Only admins can change a ticket's price after creation. Rounded before comparing because
            # the DB value is a Decimal and the input is a float.
            if current_user.role == UserRole.manager and round(float(db_tt.price), 2) != round(data.price, 2):
                raise ForbiddenError("Managers cannot change ticket price after creation — ask an admin")
            db_tt.price = data.price
        commit_or_raise(db)
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
