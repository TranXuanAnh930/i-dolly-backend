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
    """Result codes returned by IdolService._validate_refs."""
    company_not_found = "company_not_found"
    group_not_found = "group_not_found"
    company_mismatch = "company_mismatch"
    group_inactive = "group_inactive"
    color_not_found = "color_not_found"

class IdolService:

    # Eager-load options for IdolWithPositions. Built on call rather than at import, since this
    # module is imported before every model is registered.
    @staticmethod
    def _with_positions_and_color() -> tuple[Any, ...]:
        return (
            selectinload(Idol.idol_positions).joinedload(IdolPosition.position),
            selectinload(Idol.color),
            joinedload(Idol.group),
        )

    # Raises NotFoundError (missing referenced row), BadRequestError (group belongs to another
    # company, or group is inactive) and ForbiddenError (manager outside their company).
    # _validate_refs returns a _RefIssue so callers can override its result before raising.

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
            # An idol's company must match its group's company.
            if group.company_id != company_id:
                return _RefIssue.company_mismatch
            # Inactive groups can't gain new members.
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
    def get_idols(db: Session) -> list[Idol]:
        # Public list: active idols only.
        return db.query(Idol).filter(Idol.is_active.is_(True)).all()

    @staticmethod
    def get_idol(db: Session, id: uuid.UUID) -> Idol | None:
        # Not filtered by is_active, so manager forms can load deactivated idols.
        return db.get(Idol, id)

    # --- page-shaped reads ---

    @staticmethod
    def get_members_page(db: Session) -> MembersPageRead | None:
        # Active idols only; the group dropdown lists active groups only.
        idols = db.query(Idol).options(*IdolService._with_positions_and_color()).filter(Idol.is_active.is_(True)).all()
        if not idols:
            return None
        groups = db.query(Group).filter(Group.is_active.is_(True)).all()
        return MembersPageRead(idols=idols, groups=groups)

    @staticmethod
    def get_idol_detail(db: Session, id: uuid.UUID) -> IdolDetailRead | None:
        # Public profile: a deactivated idol is treated as not found.
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

    # --- manager/admin settings pages (an empty list is a normal result, not a 404)

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
        # company_id can't be changed here, so validate group/color against the existing company.
        error = IdolService._validate_refs(db, db_idol.company_id, data.group_id, data.color_id)
        # IdolUpdate resends group_id on every edit; staying in an already-joined group that has
        # since been deactivated is allowed, only moving into an inactive group is rejected.
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
        # Soft delete: concert and product history references the idol.
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
        """Replace only the idol's profile image URL."""
        db_idol = db.get(Idol, id)
        if not db_idol:
            raise NotFoundError("Idol not found")
        if IdolService._manager_scope_violation(current_user, db_idol.company_id):
            raise ForbiddenError("Managers can only manage idols for their own company")
        db_idol.profile_image_url = image_url
        db.commit()
        db.refresh(db_idol)
        return db_idol
