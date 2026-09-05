import uuid
from sqlalchemy.orm import Session
from app.schema.idol import IdolCreate, IdolUpdate
from app.db.models.idol import Idol
from app.db.models.group import Group
from app.db.models.management_company import ManagementCompany
from app.db.models.idol_color import IdolColor
from app.db.models.user import Users

# Sentinel convention for this module (all mutating functions): "not_found" =
# a referenced row (company/group/color/idol) doesn't exist at all (-> 404 in
# the router); "company_mismatch" = group_id points at a group belonging to a
# DIFFERENT company than company_id (-> 400, database-design.md §3.4);
# "forbidden" = everything above is valid, but the caller is a manager acting
# outside their own company_id (-> 403, database-design.md §4's "Not yet
# done" note — now done). A plain admin never hits "forbidden".

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def _validate_refs(db: Session, company_id: uuid.UUID, group_id: uuid.UUID | None, color_id: uuid.UUID | None):
    company = db.get(ManagementCompany, company_id)
    if not company:
        return "company_not_found"
    if group_id is not None:
        group = db.get(Group, group_id)
        if not group:
            return "group_not_found"
        # App-level invariant (database-design.md §3.4, not a DB constraint,
        # matching this codebase's existing service-layer cross-field checks):
        # if group_id is set, the idol's company_id must equal that group's
        # company_id.
        if group.company_id != company_id:
            return "company_mismatch"
    if color_id is not None:
        color = db.get(IdolColor, color_id)
        if not color:
            return "color_not_found"
    return None

def add_idol(db: Session, idol: IdolCreate, current_user: Users):
    if _manager_scope_violation(current_user, idol.company_id):
        return "forbidden"
    error = _validate_refs(db, idol.company_id, idol.group_id, idol.color_id)
    if error == "company_mismatch":
        return "company_mismatch"
    if error is not None:
        return "not_found"
    db_idol = Idol(**idol.model_dump())
    db.add(db_idol)
    db.commit()
    db.refresh(db_idol)
    return db_idol

def get_idols(db: Session):
    result = db.query(Idol).all()
    if not result:
        return False
    return result

def get_idol(db: Session, id: uuid.UUID):
    return db.get(Idol, id)

def update_idol(db: Session, id: uuid.UUID, data: IdolUpdate, current_user: Users):
    db_idol = db.get(Idol, id)
    if not db_idol:
        return "not_found"
    if _manager_scope_violation(current_user, db_idol.company_id):
        return "forbidden"
    # company_id is not part of IdolUpdate — reassigning an idol to a
    # different company is a bigger operation than a profile edit and isn't
    # exposed here; validate group/color against the idol's EXISTING company.
    error = _validate_refs(db, db_idol.company_id, data.group_id, data.color_id)
    if error == "company_mismatch":
        return "company_mismatch"
    if error is not None:
        return "not_found"
    db_idol.name = data.name
    db_idol.group_id = data.group_id
    db_idol.date_of_birth = data.date_of_birth
    db_idol.hometown = data.hometown
    db_idol.color_id = data.color_id
    db_idol.short_intro = data.short_intro
    db_idol.long_description = data.long_description
    db_idol.profile_image_url = data.profile_image_url
    db.commit()
    db.refresh(db_idol)
    return db_idol

def delete_idol(db: Session, id: uuid.UUID, current_user: Users):
    db_idol = db.get(Idol, id)
    if not db_idol:
        return "not_found"
    if _manager_scope_violation(current_user, db_idol.company_id):
        return "forbidden"
    db.delete(db_idol)
    db.commit()
    return True

def set_idol_image(db: Session, id: uuid.UUID, image_url: str, current_user: Users):
    """Used by POST /idols/{id}/image — updates only profile_image_url,
    leaving every other field untouched (update_idol replaces the whole
    profile from an IdolUpdate, which isn't what a plain image swap wants)."""
    db_idol = db.get(Idol, id)
    if not db_idol:
        return "not_found"
    if _manager_scope_violation(current_user, db_idol.company_id):
        return "forbidden"
    db_idol.profile_image_url = image_url
    db.commit()
    db.refresh(db_idol)
    return db_idol
