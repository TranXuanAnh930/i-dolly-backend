import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models.identity import Users
from app.db.models.talent import Idol, IdolPosition, Position
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.schema.talent import IdolPositionAssign, PositionBase, PositionCreate


class PositionService:

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == "manager" and current_user.company_id != company_id

    @staticmethod
    def add_position(db: Session, position: PositionCreate) -> Position | Literal[False]:
        db_position = Position(**position.model_dump())
        if not db_position:
            return False
        db.add(db_position)
        db.commit()
        db.refresh(db_position)
        return db_position

    @staticmethod
    def get_positions(db: Session) -> list[Position] | Literal[False]:
        result = db.query(Position).all()
        if not result:
            return False
        return result

    @staticmethod
    def update_position(db: Session, id: uuid.UUID, data: PositionBase) -> Position | Literal[False]:
        db_position = db.get(Position, id)
        if not db_position:
            return False
        db_position.name = data.name
        db.commit()
        db.refresh(db_position)
        return db_position

    @staticmethod
    def delete_position(db: Session, id: uuid.UUID) -> bool:
        db_position = db.get(Position, id)
        if not db_position:
            return False
        db.delete(db_position)
        db.commit()
        return True

    # --- idol_positions (join table) ---
    # Company-scoped by the IDOL, the same way group/idol CRUD is (§4): a
    # manager can only assign/change/remove a position on an idol belonging to
    # their own company. NotFoundError -> 404, ForbiddenError (manager, wrong
    # company) -> 403, BadRequestError (assign only, link already exists) -> 400.

    @staticmethod
    def assign_idol_position(db: Session, data: IdolPositionAssign, current_user: Users) -> IdolPosition:
        idol = db.get(Idol, data.idol_id)
        position = db.get(Position, data.position_id)
        if not idol or not position:
            raise NotFoundError("Idol or position not found")
        if PositionService._manager_scope_violation(current_user, idol.company_id):
            raise ForbiddenError("Managers can only manage positions for idols in their own company")
        existing = db.get(IdolPosition, (data.idol_id, data.position_id))
        if existing:
            raise BadRequestError("Idol already has this position — use PUT to change is_primary")
        db_link = IdolPosition(
            idol_id=data.idol_id,
            position_id=data.position_id,
            is_primary=data.is_primary,
        )
        db.add(db_link)
        db.commit()
        db.refresh(db_link)
        return db_link

    @staticmethod
    def get_idol_positions(db: Session, idol_id: uuid.UUID) -> list[IdolPosition] | Literal[False]:
        result = db.query(IdolPosition).filter(IdolPosition.idol_id == idol_id).all()
        if not result:
            return False
        return result

    @staticmethod
    def get_all_idol_positions(db: Session) -> list[IdolPosition] | Literal[False]:
        result = db.query(IdolPosition).all()
        if not result:
            return False
        return result

    @staticmethod
    def update_idol_position_primary(db: Session, idol_id: uuid.UUID, position_id: uuid.UUID, is_primary: bool, current_user: Users) -> IdolPosition:
        link = db.get(IdolPosition, (idol_id, position_id))
        if not link:
            raise NotFoundError("This idol/position assignment doesn't exist")
        if PositionService._manager_scope_violation(current_user, link.idol.company_id):
            raise ForbiddenError("Managers can only manage positions for idols in their own company")
        link.is_primary = is_primary
        db.commit()
        db.refresh(link)
        return link

    @staticmethod
    def remove_idol_position(db: Session, idol_id: uuid.UUID, position_id: uuid.UUID, current_user: Users) -> Literal[True]:
        link = db.get(IdolPosition, (idol_id, position_id))
        if not link:
            raise NotFoundError("This idol/position assignment doesn't exist")
        if PositionService._manager_scope_violation(current_user, link.idol.company_id):
            raise ForbiddenError("Managers can only manage positions for idols in their own company")
        db.delete(link)
        db.commit()
        return True
