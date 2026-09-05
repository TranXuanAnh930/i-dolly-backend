from sqlalchemy.orm import Session
from app.schema.lightstick_detail import LightstickDetailCreate, LightstickDetailUpdate
from app.db.models.lightstick_detail import LightstickDetail
from app.db.models.products import Product
from app.db.models.idol import Idol
from app.db.models.group import Group
from app.db.models.idol_color import IdolColor
from app.db.models.user import Users
from app.exception.db_triggers import commit_or_raise

# Same dual-FK scoping as album_details.

def _manager_scope_violation(current_user: Users, company_id: int) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def _resolve_company_id(db: Session, idol_id, group_id):
    if idol_id is not None:
        idol = db.get(Idol, idol_id)
        return idol.company_id if idol else None
    if group_id is not None:
        group = db.get(Group, group_id)
        return group.company_id if group else None
    return None

def add_lightstick_detail(db: Session, data: LightstickDetailCreate, current_user: Users):
    if not db.get(Product, data.product_id):
        return "not_found"
    if db.get(LightstickDetail, data.product_id):
        return "conflict"
    if data.color_id is not None and not db.get(IdolColor, data.color_id):
        return "not_found"
    company_id = _resolve_company_id(db, data.idol_id, data.group_id)
    if company_id is None:
        return "not_found"
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db_ls = LightstickDetail(**data.model_dump())
    db.add(db_ls)
    commit_or_raise(db)  # trg_lightstick_details_exclusive_kind
    db.refresh(db_ls)
    return db_ls

def get_lightstick_detail(db: Session, product_id: int):
    return db.get(LightstickDetail, product_id)

def get_lightstick_details(db: Session):
    result = db.query(LightstickDetail).all()
    if not result:
        return False
    return result

def update_lightstick_detail(db: Session, product_id: int, data: LightstickDetailUpdate, current_user: Users):
    db_ls = db.get(LightstickDetail, product_id)
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

def delete_lightstick_detail(db: Session, product_id: int, current_user: Users):
    db_ls = db.get(LightstickDetail, product_id)
    if not db_ls:
        return "not_found"
    company_id = _resolve_company_id(db, db_ls.idol_id, db_ls.group_id)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db.delete(db_ls)
    db.commit()
    return True
