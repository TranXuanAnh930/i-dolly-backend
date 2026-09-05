from sqlalchemy.orm import Session
from app.schema.album_detail import AlbumDetailCreate, AlbumDetailUpdate
from app.db.models.album_detail import AlbumDetail
from app.db.models.products import Product
from app.db.models.idol import Idol
from app.db.models.group import Group
from app.db.models.user import Users
from app.exception.db_triggers import commit_or_raise

# Company-scoped via whichever of idol_id/group_id is set on the row (the
# "dual-FK scoping" case flagged in database-design.md — more complex than
# concerts' direct company_id, same idea as lottery_campaigns' two-level
# join but resolved by "which FK is non-null" instead of a fixed path).

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

def add_album_detail(db: Session, data: AlbumDetailCreate, current_user: Users):
    if not db.get(Product, data.product_id):
        return "not_found"
    if db.get(AlbumDetail, data.product_id):
        return "conflict"  # already has album_details
    company_id = _resolve_company_id(db, data.idol_id, data.group_id)
    if company_id is None:
        return "not_found"  # referenced idol/group doesn't exist
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db_album = AlbumDetail(**data.model_dump())
    db.add(db_album)
    commit_or_raise(db)  # trg_album_details_exclusive_kind
    db.refresh(db_album)
    return db_album

def get_album_detail(db: Session, product_id: int):
    return db.get(AlbumDetail, product_id)

def get_album_details(db: Session):
    result = db.query(AlbumDetail).all()
    if not result:
        return False
    return result

def update_album_detail(db: Session, product_id: int, data: AlbumDetailUpdate, current_user: Users):
    db_album = db.get(AlbumDetail, product_id)
    if not db_album:
        return "not_found"
    company_id = _resolve_company_id(db, db_album.idol_id, db_album.group_id)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db_album.release_date = data.release_date
    db_album.track_count = data.track_count
    db_album.format = data.format
    db_album.cover_image_url = data.cover_image_url
    db.commit()
    db.refresh(db_album)
    return db_album

def delete_album_detail(db: Session, product_id: int, current_user: Users):
    db_album = db.get(AlbumDetail, product_id)
    if not db_album:
        return "not_found"
    company_id = _resolve_company_id(db, db_album.idol_id, db_album.group_id)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db.delete(db_album)
    db.commit()
    return True
