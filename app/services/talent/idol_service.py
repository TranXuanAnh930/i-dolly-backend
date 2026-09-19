import uuid
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models.identity import Users
from app.db.models.talent import Group, Idol, IdolColor, IdolPosition, ManagementCompany
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.schema.identity import UserRole
from app.schema.talent import (
    IdolCreate,
    IdolDetailRead,
    IdolUpdate,
    ManagerIdolFormPageRead,
    ManagerIdolsPageRead,
    MembersPageRead,
)


class _RefIssue(str, Enum):
    """Private outcome type for `IdolService._validate_refs` — not a model column's value set, so
    it stays local to this module rather than in `app/schema/`, same reasoning as any other
    private-helper sentinel (`docs/architecture.md` §2)."""
    company_not_found = "company_not_found"
    group_not_found = "group_not_found"
    company_mismatch = "company_mismatch"
    group_inactive = "group_inactive"
    color_not_found = "color_not_found"

class IdolService:

    # Eager-loads exactly what IdolWithPositions needs so a page-shaped endpoint returns
    # fully-formed idols in one query. Built lazily (called, not evaluated at import time) —
    # this module loads early in main.py's router import chain, before routers that register
    # unrelated models SQLAlchemy needs to resolve relationships have run.
    @staticmethod
    def _with_positions_and_color() -> tuple[Any, ...]:
        return (
            selectinload(Idol.idol_positions).joinedload(IdolPosition.position),
            selectinload(Idol.color),
            joinedload(Idol.group),
        )

    # Error convention: NotFoundError for a missing referenced row; BadRequestError for
    # "company_mismatch" (group_id belongs to a different company) or "group_inactive"
    # (deactivated group, blocks new membership); ForbiddenError for a manager acting outside
    # their own company. _validate_refs stays a private, sentinel-returning helper — its callers
    # need to inspect and sometimes override its result before deciding it's an error.

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == UserRole.manager and current_user.company_id != company_id

    @staticmethod
    def _validate_refs(db: Session, company_id: uuid.UUID, group_id: uuid.UUID | None, color_id: uuid.UUID | None) -> _RefIssue | None:
        company = db.get(ManagementCompany, company_id)
        if not company:
            return _RefIssue.company_not_found
        if group_id is not None:
            group = db.get(Group, group_id)
            if not group:
                return _RefIssue.group_not_found
            # App-level invariant (database-design.md §3.4, not a DB constraint,
            # matching this codebase's existing service-layer cross-field checks):
            # if group_id is set, the idol's company_id must equal that group's
            # company_id.
            if group.company_id != company_id:
                return _RefIssue.company_mismatch
            # A deactivated group is closed to new/changed membership — it can
            # still be READ (existing members, past products/events), but an
            # idol can't be newly assigned into it via add/update.
            if not group.is_active:
                return _RefIssue.group_inactive
        if color_id is not None:
            color = db.get(IdolColor, color_id)
            if not color:
                return _RefIssue.color_not_found
        return None

    @staticmethod
    def add_idol(db: Session, idol: IdolCreate, current_user: Users) -> Idol:
        if IdolService._manager_scope_violation(current_user, idol.company_id):
            raise ForbiddenError("Managers can only manage idols for their own company")
        error = IdolService._validate_refs(db, idol.company_id, idol.group_id, idol.color_id)
        if error == _RefIssue.company_mismatch:
            raise BadRequestError("group_id belongs to a different company than company_id")
        if error == _RefIssue.group_inactive:
            raise BadRequestError("Cannot assign an idol into a deactivated group")
        if error is not None:
            raise NotFoundError("Management company, group, or idol color not found")
        db_idol = Idol(**idol.model_dump())
        db.add(db_idol)
        db.commit()
        db.refresh(db_idol)
        return db_idol

    @staticmethod
    def get_idols(db: Session) -> list[Idol] | None:
        # Public "browse all idols" list — deactivated idols don't belong on a
        # store-facing listing (database-design.md §3.4).
        result = db.query(Idol).filter(Idol.is_active.is_(True)).all()
        if not result:
            return None
        return result

    @staticmethod
    def get_idol(db: Session, id: uuid.UUID) -> Idol | None:
        # Deliberately NOT filtered by is_active — see group_service.get_group's
        # equivalent comment; a manager's edit form needs this to load a
        # deactivated idol.
        return db.get(Idol, id)

    # --- page-shaped reads (see idol.py schema's equivalent comment) ---

    @staticmethod
    def get_members_page(db: Session) -> MembersPageRead | None:
        # Store-facing browse page — same is_active filter as get_idols, plus
        # the group-unit dropdown only offers active groups.
        idols = db.query(Idol).options(*IdolService._with_positions_and_color()).filter(Idol.is_active.is_(True)).all()
        if not idols:
            return None
        groups = db.query(Group).filter(Group.is_active.is_(True)).all()
        return MembersPageRead(idols=idols, groups=groups)

    @staticmethod
    def get_idol_detail(db: Session, id: uuid.UUID) -> IdolDetailRead | None:
        # Public idol profile page — a deactivated idol reads as "not found"
        # here, same as get_idols/get_members_page; only the manager/admin
        # settings surfaces (get_manager_idols_page, plain get_idol) still see it.
        idol = (
            db.query(Idol)
            .options(*IdolService._with_positions_and_color())
            .filter(Idol.id == id, Idol.is_active.is_(True))
            .first()
        )
        if not idol:
            return None
        group = db.get(Group, idol.group_id) if idol.group_id else None
        siblings_query = db.query(Idol).filter(Idol.id != id, Idol.is_active.is_(True))
        siblings_query = siblings_query.filter(Idol.group_id == idol.group_id) if idol.group_id else siblings_query.filter(Idol.group_id.is_(None))
        siblings = siblings_query.options(*IdolService._with_positions_and_color()).all()
        return IdolDetailRead(idol=idol, group=group, siblings=siblings)

    # --- manager/admin settings pages (see idol.py schema's equivalent comment
    # — empty lists here are a normal state, not a 404).

    @staticmethod
    def get_manager_idols_page(db: Session) -> ManagerIdolsPageRead:
        return ManagerIdolsPageRead(idols=db.query(Idol).all(), groups=db.query(Group).all())

    @staticmethod
    def get_manager_idol_form_page(db: Session) -> ManagerIdolFormPageRead:
        return ManagerIdolFormPageRead(
            idols=db.query(Idol).all(),
            groups=db.query(Group).all(),
            colors=db.query(IdolColor).all(),
        )

    @staticmethod
    def update_idol(db: Session, id: uuid.UUID, data: IdolUpdate, current_user: Users) -> Idol:
        db_idol = db.get(Idol, id)
        if not db_idol:
            raise NotFoundError("Idol not found")
        if IdolService._manager_scope_violation(current_user, db_idol.company_id):
            raise ForbiddenError("Managers can only manage idols for their own company")
        # company_id is not part of IdolUpdate — reassigning an idol to a
        # different company is a bigger operation than a profile edit and isn't
        # exposed here; validate group/color against the idol's EXISTING company.
        error = IdolService._validate_refs(db, db_idol.company_id, data.group_id, data.color_id)
        # IdolUpdate is a full-replace PUT, so data.group_id is resent unchanged
        # on every ordinary edit — if the idol was already a member before its
        # group got deactivated, that's not a new assignment and shouldn't block
        # the rest of the edit. Only a genuine move INTO a deactivated group
        # (data.group_id != the idol's current group_id) is rejected.
        if error == _RefIssue.group_inactive and data.group_id == db_idol.group_id:
            error = None
        if error == _RefIssue.company_mismatch:
            raise BadRequestError("group_id belongs to a different company than company_id")
        if error == _RefIssue.group_inactive:
            raise BadRequestError("Cannot assign an idol into a deactivated group")
        if error is not None:
            raise NotFoundError("Idol, group, or idol color not found")
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

    @staticmethod
    def delete_idol(db: Session, id: uuid.UUID, current_user: Users) -> Idol:
        # Soft delete, not db.delete(): concert_performers CASCADEs off
        # idols.id and album_details/merch_details SET NULL their idol_id —
        # hard-deleting an idol with concert or product history would destroy
        # or orphan that history. Deactivating in place keeps every FK target
        # alive (database-design.md §3.4).
        db_idol = db.get(Idol, id)
        if not db_idol:
            raise NotFoundError("Idol not found")
        if IdolService._manager_scope_violation(current_user, db_idol.company_id):
            raise ForbiddenError("Managers can only manage idols for their own company")
        db_idol.is_active = False
        db.commit()
        return db_idol

    @staticmethod
    def reactivate_idol(db: Session, id: uuid.UUID, current_user: Users) -> Idol:
        db_idol = db.get(Idol, id)
        if not db_idol:
            raise NotFoundError("Idol not found")
        if IdolService._manager_scope_violation(current_user, db_idol.company_id):
            raise ForbiddenError("Managers can only manage idols for their own company")
        db_idol.is_active = True
        db.commit()
        db.refresh(db_idol)
        return db_idol

    @staticmethod
    def set_idol_image(db: Session, id: uuid.UUID, image_url: str, current_user: Users) -> Idol:
        """Used by POST /idols/{id}/image — updates only profile_image_url,
        leaving every other field untouched (update_idol replaces the whole
        profile from an IdolUpdate, which isn't what a plain image swap wants)."""
        db_idol = db.get(Idol, id)
        if not db_idol:
            raise NotFoundError("Idol not found")
        if IdolService._manager_scope_violation(current_user, db_idol.company_id):
            raise ForbiddenError("Managers can only manage idols for their own company")
        db_idol.profile_image_url = image_url
        db.commit()
        db.refresh(db_idol)
        return db_idol
