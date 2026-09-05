import uuid
from sqlalchemy.orm import Session
from app.schema.position import PositionBase, PositionCreate, IdolPositionAssign
from app.db.models.position import Position, IdolPosition
from app.db.models.idol import Idol
from app.db.models.user import Users

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def add_position(db: Session, position: PositionCreate):
    db_position = Position(**position.model_dump())
    if not db_position:
        return False
    db.add(db_position)
    db.commit()
    db.refresh(db_position)
    return db_position

def get_positions(db: Session):
    result = db.query(Position).all()
    if not result:
        return False
    return result

def update_position(db: Session, id: uuid.UUID, data: PositionBase):
    db_position = db.get(Position, id)
    if not db_position:
        return False
    db_position.name = data.name
    db.commit()
    db.refresh(db_position)
    return db_position

def delete_position(db: Session, id: uuid.UUID):
    db_position = db.get(Position, id)
    if not db_position:
        return False
    db.delete(db_position)
    db.commit()
    return True

# --- idol_positions (join table) ---
# Company-scoped by the IDOL, the same way group/idol CRUD is (§4): a
# manager can only assign/change/remove a position on an idol belonging to
# their own company. Sentinel convention: "not_found" -> 404, "forbidden"
# (manager, wrong company) -> 403, "conflict" (assign only, link already
# exists) -> 400.

def assign_idol_position(db: Session, data: IdolPositionAssign, current_user: Users):
    idol = db.get(Idol, data.idol_id)
    position = db.get(Position, data.position_id)
    if not idol or not position:
        return "not_found"
    if _manager_scope_violation(current_user, idol.company_id):
        return "forbidden"
    existing = db.get(IdolPosition, (data.idol_id, data.position_id))
    if existing:
        return "conflict"  # already assigned -> use update_idol_position_primary instead
    db_link = IdolPosition(
        idol_id=data.idol_id,
        position_id=data.position_id,
        is_primary=data.is_primary,
    )
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link

def get_idol_positions(db: Session, idol_id: uuid.UUID):
    result = db.query(IdolPosition).filter(IdolPosition.idol_id == idol_id).all()
    if not result:
        return False
    return result

def update_idol_position_primary(db: Session, idol_id: uuid.UUID, position_id: uuid.UUID, is_primary: bool, current_user: Users):
    link = db.get(IdolPosition, (idol_id, position_id))
    if not link:
        return "not_found"
    if _manager_scope_violation(current_user, link.idol.company_id):
        return "forbidden"
    link.is_primary = is_primary
    db.commit()
    db.refresh(link)
    return link

def remove_idol_position(db: Session, idol_id: uuid.UUID, position_id: uuid.UUID, current_user: Users):
    link = db.get(IdolPosition, (idol_id, position_id))
    if not link:
        return "not_found"
    if _manager_scope_violation(current_user, link.idol.company_id):
        return "forbidden"
    db.delete(link)
    db.commit()
    return True
