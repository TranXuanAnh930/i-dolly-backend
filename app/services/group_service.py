import uuid
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from app.schema.group import GroupCreate, GroupUpdate
from app.db.models.group import Group
from app.db.models.management_company import ManagementCompany
from app.db.models.idol import Idol
from app.db.models.concert import Concert, ConcertPerformer
from app.db.models.products import Product
from app.db.models.user import Users
from app.services.product_service import _build_product_cards
from app.services.idol_service import _with_positions_and_color

# Sentinel convention for this module: "not_found" = a referenced row doesn't
# exist (-> 404 in the router); "forbidden" = the row(s) exist but the caller
# is a manager acting outside their own company_id (-> 403). A plain admin
# is never scoped — only `role == "manager"` triggers the company check
# (database-design.md §4: "Not yet done" note, now done for groups/idols).

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def add_group(db: Session, group: GroupCreate, current_user: Users):
    if _manager_scope_violation(current_user, group.company_id):
        return "forbidden"
    company = db.get(ManagementCompany, group.company_id)
    if not company:
        return "not_found"  # company_id doesn't exist
    db_group = Group(**group.model_dump())
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group

def get_groups(db: Session):
    result = db.query(Group).all()
    if not result:
        return False
    return result

def get_group(db: Session, id: uuid.UUID):
    return db.get(Group, id)

def update_group(db: Session, id: uuid.UUID, data: GroupUpdate, current_user: Users):
    db_group = db.get(Group, id)
    if not db_group:
        return "not_found"
    if _manager_scope_violation(current_user, db_group.company_id):
        return "forbidden"
    db_group.name = data.name
    db_group.debut_date = data.debut_date
    db_group.description = data.description
    db.commit()
    db.refresh(db_group)
    return db_group

def delete_group(db: Session, id: uuid.UUID, current_user: Users):
    db_group = db.get(Group, id)
    if not db_group:
        return "not_found"
    if _manager_scope_violation(current_user, db_group.company_id):
        return "forbidden"
    db.delete(db_group)
    db.commit()
    return True

# --- page-shaped reads (see idol_service.py's equivalent comment) ---

def get_groups_page(db: Session):
    groups = db.query(Group).all()
    if not groups:
        return False
    counts = dict(
        db.query(Idol.group_id, func.count(Idol.id))
        .filter(Idol.group_id.isnot(None))
        .group_by(Idol.group_id)
        .all()
    )
    for group in groups:
        group.member_count = counts.get(group.id, 0)
    return {"groups": groups}

def get_group_detail(db: Session, id: uuid.UUID):
    group = db.get(Group, id)
    if not group:
        return False

    members = (
        db.query(Idol)
        .options(*_with_positions_and_color())
        .filter(Idol.group_id == id)
        .all()
    )

    # A concert "belongs" to this group only via one of its performer
    # credits — no direct FK from concerts to groups.
    events = (
        db.query(Concert)
        .join(ConcertPerformer, ConcertPerformer.concert_id == Concert.id)
        .filter(ConcertPerformer.group_id == id)
        .options(joinedload(Concert.venue))
        .distinct()
        .order_by(Concert.event_datetime)
        .all()
    )

    # Every product whose resolved artist (album_details/merch_details
    # FK, or a name-prefix match for plain merch with neither — see
    # _build_product_cards) is this group. Built from every product rather
    # than a direct FK filter so plain merch (e.g. a tour hoodie with no
    # album_details/merch_details row at all) still shows up here,
    # exactly as it does on the store grid.
    all_products = db.query(Product).options(joinedload(Product.category)).all()
    products = [
        card for card in _build_product_cards(db, all_products)
        if card["artist"] and card["artist"]["type"] == "group" and card["artist"]["id"] == id
    ]

    return {
        "group": group,
        "members": members,
        "events": events,
        "products": products,
    }

# --- manager/admin settings page (see idol_service.py's equivalent comment
# — an empty list here is a normal state, not a 404).

def get_manager_groups_page(db: Session):
    return {"groups": db.query(Group).all()}
