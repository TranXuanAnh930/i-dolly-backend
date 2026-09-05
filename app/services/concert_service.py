import uuid
from sqlalchemy.orm import Session, joinedload, selectinload
from app.schema.concert import ConcertCreate, ConcertUpdate, ConcertPerformerAssign
from app.db.models.concert import Concert, ConcertPerformer
from app.db.models.management_company import ManagementCompany
from app.db.models.venue import Venue
from app.db.models.ticket_type import TicketType
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

def get_all_performers(db: Session):
    result = db.query(ConcertPerformer).all()
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

# --- page-shaped reads (see idol_service.py's equivalent comment) ---

def get_events_page(db: Session):
    concerts = db.query(Concert).options(joinedload(Concert.venue)).all()
    if not concerts:
        return False
    return {"concerts": concerts}

def _lineup_idol(idol: Idol):
    return {
        "id": idol.id,
        "name": idol.name,
        "profile_image_url": idol.profile_image_url,
        "color_hex": idol.color.hex_code if idol.color else None,
    }

def get_concert_detail(db: Session, id: uuid.UUID):
    concert = db.query(Concert).options(joinedload(Concert.venue)).filter(Concert.id == id).first()
    if not concert:
        return False
    ticket_types = db.query(TicketType).filter(TicketType.concert_id == id).all()
    performers = (
        db.query(ConcertPerformer)
        .options(joinedload(ConcertPerformer.idol).selectinload(Idol.color), joinedload(ConcertPerformer.group))
        .filter(ConcertPerformer.concert_id == id)
        .all()
    )
    # A group credit expands to that group's current members, a solo credit
    # is just that one idol — de-duplicated in case the same idol shows up
    # via both a solo and a group credit (mirrors the previous client-side
    # concertsStore.lineupForConcert getter).
    seen_idol_ids = set()
    lineup = []
    seen_group_ids = set()
    performing_groups = []
    for performer in performers:
        if performer.group_id and performer.group:
            if performer.group_id not in seen_group_ids:
                seen_group_ids.add(performer.group_id)
                performing_groups.append({"id": performer.group.id, "name": performer.group.name})
            members = db.query(Idol).options(selectinload(Idol.color)).filter(Idol.group_id == performer.group_id).all()
            for member in members:
                if member.id not in seen_idol_ids:
                    seen_idol_ids.add(member.id)
                    lineup.append(_lineup_idol(member))
        elif performer.idol_id and performer.idol:
            if performer.idol_id not in seen_idol_ids:
                seen_idol_ids.add(performer.idol_id)
                lineup.append(_lineup_idol(performer.idol))
    return {
        "concert": concert,
        "venue": concert.venue,
        "ticket_types": ticket_types,
        "lineup": lineup,
        "performing_groups": performing_groups,
    }
