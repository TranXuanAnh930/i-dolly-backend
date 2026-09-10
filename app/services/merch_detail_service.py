import uuid
from sqlalchemy.orm import Session
from app.schema.merch_detail import MerchDetailCreate, MerchDetailUpdate
from app.db.models.merch_detail import MerchDetail
from app.db.models.products import Product
from app.db.models.idol import Idol
from app.db.models.group import Group
from app.db.models.idol_color import IdolColor
from app.db.models.user import Users
from app.exception.db_triggers import commit_or_raise

# Same dual-FK scoping as album_details.

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def _resolve_company_id(db: Session, idol_id, group_id):
    if idol_id is not None:
        idol = db.get(Idol, idol_id)
        return idol.company_id if idol else None
    if group_id is not None:
        group = db.get(Group, group_id)
        return group.company_id if group else None
    return None

def _artist_active_or_missing(db: Session, idol_id, group_id) -> bool:
    # Same rule as album_detail_service's equivalent helper.
    if idol_id is not None:
        idol = db.get(Idol, idol_id)
        return idol is None or idol.is_active
    if group_id is not None:
        group = db.get(Group, group_id)
        return group is None or group.is_active
    return True

def add_merch_detail(db: Session, data: MerchDetailCreate, current_user: Users):
    if not db.get(Product, data.product_id):
        return "not_found"
    if db.get(MerchDetail, data.product_id):
        return "conflict"
    if data.color_id is not None and not db.get(IdolColor, data.color_id):
        return "not_found"
    if not _artist_active_or_missing(db, data.idol_id, data.group_id):
        return "artist_inactive"
    company_id = _resolve_company_id(db, data.idol_id, data.group_id)
    if company_id is None:
        return "not_found"
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db_ls = MerchDetail(**data.model_dump())
    db.add(db_ls)
    commit_or_raise(db)  # trg_merch_details_exclusive_kind
    db.refresh(db_ls)
    return db_ls

def get_merch_detail(db: Session, product_id: uuid.UUID):
    return db.get(MerchDetail, product_id)

def get_merch_details(db: Session):
    result = db.query(MerchDetail).all()
    if not result:
        return False
    return result

def update_merch_detail(db: Session, product_id: uuid.UUID, data: MerchDetailUpdate, current_user: Users):
    db_ls = db.get(MerchDetail, product_id)
    if not db_ls:
        return "not_found"
    company_id = _resolve_company_id(db, db_ls.idol_id, db_ls.group_id)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    if data.color_id is not None and not db.get(IdolColor, data.color_id):
        return "not_found"
    db_ls.edition = data.edition
    db_ls.color_id = data.color_id
    db.commit()
    db.refresh(db_ls)
    return db_ls

def delete_merch_detail(db: Session, product_id: uuid.UUID, current_user: Users):
    db_ls = db.get(MerchDetail, product_id)
    if not db_ls:
        return "not_found"
    company_id = _resolve_company_id(db, db_ls.idol_id, db_ls.group_id)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db.delete(db_ls)
    db.commit()
    return True
