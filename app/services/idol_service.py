import uuid

from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models.group import Group
from app.db.models.idol import Idol
from app.db.models.idol_color import IdolColor
from app.db.models.management_company import ManagementCompany
from app.db.models.position import IdolPosition
from app.db.models.user import Users
from app.schema.idol import IdolCreate, IdolUpdate


# Eager-loads exactly what IdolWithPositions needs (idol.py schema) so a
# page-shaped endpoint returns fully-formed idols in one query instead of
# the client resolving positions/color via separate lookups. Built lazily
# (called, not evaluated at import time) — selectinload()/joinedload()
# force SQLAlchemy to configure every mapper right then, and this module
# loads early in main.py's router import chain, before routers that
# register unrelated models (e.g. genre.py's AlbumGenre, referenced by a
# relationship() on AlbumDetail) have run.
def _with_positions_and_color():
    return (
        selectinload(Idol.idol_positions).joinedload(IdolPosition.position),
        selectinload(Idol.color),
        joinedload(Idol.group),
    )

# Sentinel convention for this module (all mutating functions): "not_found" =
# a referenced row (company/group/color/idol) doesn't exist at all (-> 404 in
# the router); "company_mismatch" = group_id points at a group belonging to a
# DIFFERENT company than company_id (-> 400, database-design.md §3.4);
# "group_inactive" = group_id exists and matches company_id but is
# deactivated — new/changed membership into it is blocked (-> 400,
# database-design.md §3.3); "forbidden" = everything above is valid, but the
# caller is a manager acting outside their own company_id (-> 403,
# database-design.md §4's "Not yet done" note — now done). A plain admin
# never hits "forbidden".

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
        # A deactivated group is closed to new/changed membership — it can
        # still be READ (existing members, past products/events), but an
        # idol can't be newly assigned into it via add/update.
        if not group.is_active:
            return "group_inactive"
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
    if error == "group_inactive":
        return "group_inactive"
    if error is not None:
        return "not_found"
    db_idol = Idol(**idol.model_dump())
    db.add(db_idol)
    db.commit()
    db.refresh(db_idol)
    return db_idol

def get_idols(db: Session):
    # Public "browse all idols" list — deactivated idols don't belong on a
    # store-facing listing (database-design.md §3.4).
    result = db.query(Idol).filter(Idol.is_active.is_(True)).all()
    if not result:
        return False
    return result

def get_idol(db: Session, id: uuid.UUID):
    # Deliberately NOT filtered by is_active — see group_service.get_group's
    # equivalent comment; a manager's edit form needs this to load a
    # deactivated idol.
    return db.get(Idol, id)

# --- page-shaped reads (see idol.py schema's equivalent comment) ---

def get_members_page(db: Session):
    # Store-facing browse page — same is_active filter as get_idols, plus
    # the group-unit dropdown only offers active groups.
    idols = db.query(Idol).options(*_with_positions_and_color()).filter(Idol.is_active.is_(True)).all()
    if not idols:
        return False
    groups = db.query(Group).filter(Group.is_active.is_(True)).all()
    return {"idols": idols, "groups": groups}

def get_idol_detail(db: Session, id: uuid.UUID):
    # Public idol profile page — a deactivated idol reads as "not found"
    # here, same as get_idols/get_members_page; only the manager/admin
    # settings surfaces (get_manager_idols_page, plain get_idol) still see it.
    idol = (
        db.query(Idol)
        .options(*_with_positions_and_color())
        .filter(Idol.id == id, Idol.is_active.is_(True))
        .first()
    )
    if not idol:
        return False
    group = db.get(Group, idol.group_id) if idol.group_id else None
    siblings_query = db.query(Idol).filter(Idol.id != id, Idol.is_active.is_(True))
    siblings_query = siblings_query.filter(Idol.group_id == idol.group_id) if idol.group_id else siblings_query.filter(Idol.group_id.is_(None))
    siblings = siblings_query.options(*_with_positions_and_color()).all()
    return {"idol": idol, "group": group, "siblings": siblings}

# --- manager/admin settings pages (see idol.py schema's equivalent comment
# — empty lists here are a normal state, not a 404).

def get_manager_idols_page(db: Session):
    return {"idols": db.query(Idol).all(), "groups": db.query(Group).all()}

def get_manager_idol_form_page(db: Session):
    return {
        "idols": db.query(Idol).all(),
        "groups": db.query(Group).all(),
        "colors": db.query(IdolColor).all(),
    }

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
    # IdolUpdate is a full-replace PUT, so data.group_id is resent unchanged
    # on every ordinary edit — if the idol was already a member before its
    # group got deactivated, that's not a new assignment and shouldn't block
    # the rest of the edit. Only a genuine move INTO a deactivated group
    # (data.group_id != the idol's current group_id) is rejected.
    if error == "group_inactive" and data.group_id == db_idol.group_id:
        error = None
    if error == "company_mismatch":
        return "company_mismatch"
    if error == "group_inactive":
        return "group_inactive"
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
    # Soft delete, not db.delete(): concert_performers CASCADEs off
    # idols.id and album_details/merch_details SET NULL their idol_id —
    # hard-deleting an idol with concert or product history would destroy
    # or orphan that history. Deactivating in place keeps every FK target
    # alive (database-design.md §3.4).
    db_idol = db.get(Idol, id)
    if not db_idol:
        return "not_found"
    if _manager_scope_violation(current_user, db_idol.company_id):
        return "forbidden"
    db_idol.is_active = False
    db.commit()
    return True

def reactivate_idol(db: Session, id: uuid.UUID, current_user: Users):
    db_idol = db.get(Idol, id)
    if not db_idol:
        return "not_found"
    if _manager_scope_violation(current_user, db_idol.company_id):
        return "forbidden"
    db_idol.is_active = True
    db.commit()
    db.refresh(db_idol)
    return db_idol

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
