import uuid
from sqlalchemy.orm import Session
from app.schema.concert import ConcertCreate, ConcertUpdate, ConcertPerformerAssign
from app.db.models.concert import Concert, ConcertPerformer
from app.db.models.management_company import ManagementCompany
from app.db.models.venue import Venue
from app.db.models.idol import Idol
from app.db.models.group import Group
from app.db.models.user import Users

# Same sentinel convention as group_service/idol_service: "not_found" (404),
# "forbidden" (403, manager acting outside their own company_id).

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def add_concert(db: Session, concert: ConcertCreate, current_user: Users):
    if _manager_scope_violation(current_user, concert.company_id):
        return "forbidden"
    if not db.get(ManagementCompany, concert.company_id):
        return "not_found"
    if not db.get(Venue, concert.venue_id):
        return "not_found"
    db_concert = Concert(**concert.model_dump())
    db.add(db_concert)
    db.commit()
    db.refresh(db_concert)
    return db_concert

def get_concerts(db: Session):
    result = db.query(Concert).all()
    if not result:
        return False
    return result

def get_concert(db: Session, id: uuid.UUID):
    return db.get(Concert, id)

def update_concert(db: Session, id: uuid.UUID, data: ConcertUpdate, current_user: Users):
    db_concert = db.get(Concert, id)
    if not db_concert:
        return "not_found"
    if _manager_scope_violation(current_user, db_concert.company_id):
        return "forbidden"
    if not db.get(Venue, data.venue_id):
        return "not_found"
    db_concert.venue_id = data.venue_id
    db_concert.title = data.title
    db_concert.description = data.description
    db_concert.capacity = data.capacity
    db_concert.event_datetime = data.event_datetime
    db_concert.doors_open_at = data.doors_open_at
    if data.status is not None:
        db_concert.status = data.status
    db.commit()
    db.refresh(db_concert)
    return db_concert

def delete_concert(db: Session, id: uuid.UUID, current_user: Users):
    db_concert = db.get(Concert, id)
    if not db_concert:
        return "not_found"
    if _manager_scope_violation(current_user, db_concert.company_id):
        return "forbidden"
    db.delete(db_concert)
    db.commit()
    return True


# --- concert_performers ---

def assign_performer(db: Session, data: ConcertPerformerAssign, current_user: Users):
    if (data.idol_id is None) == (data.group_id is None):
        return "invalid"  # exactly one of idol_id/group_id, matching chk_concert_performers_one_of
    concert = db.get(Concert, data.concert_id)
    if not concert:
        return "not_found"
    if _manager_scope_violation(current_user, concert.company_id):
        return "forbidden"
    if data.idol_id is not None and not db.get(Idol, data.idol_id):
        return "not_found"
    if data.group_id is not None and not db.get(Group, data.group_id):
        return "not_found"
    db_link = ConcertPerformer(concert_id=data.concert_id, idol_id=data.idol_id, group_id=data.group_id)
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link

def get_performers(db: Session, concert_id: uuid.UUID):
    result = db.query(ConcertPerformer).filter(ConcertPerformer.concert_id == concert_id).all()
    if not result:
        return False
    return result

def remove_performer(db: Session, id: uuid.UUID, current_user: Users):
    link = db.get(ConcertPerformer, id)
    if not link:
        return "not_found"
    concert = db.get(Concert, link.concert_id)
    if _manager_scope_violation(current_user, concert.company_id):
        return "forbidden"
    db.delete(link)
    db.commit()
    return True
