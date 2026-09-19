import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models.identity import Users
from app.db.models.marketplace import AlbumDetail, Product
from app.db.models.talent import Group, Idol
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import commit_or_raise
from app.schema.marketplace import AlbumDetailCreate, AlbumDetailUpdate


class AlbumDetailService:

    # Company-scoped via whichever of idol_id/group_id is set on the row (the
    # "dual-FK scoping" case flagged in database-design.md — more complex than
    # concerts' direct company_id, same idea as lottery_campaigns' two-level
    # join but resolved by "which FK is non-null" instead of a fixed path).

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID | None) -> bool:
        return current_user.role == "manager" and current_user.company_id != company_id

    @staticmethod
    def _resolve_company_id(db: Session, idol_id: uuid.UUID | None, group_id: uuid.UUID | None) -> uuid.UUID | None:
        if idol_id is not None:
            idol = db.get(Idol, idol_id)
            return idol.company_id if idol else None
        if group_id is not None:
            group = db.get(Group, group_id)
            return group.company_id if group else None
        return None

    @staticmethod
    def _artist_active_or_missing(db: Session, idol_id: uuid.UUID | None, group_id: uuid.UUID | None) -> bool:
        # True unless the referenced idol/group exists AND is deactivated — a
        # nonexistent id is left for the "not_found" check right after this to
        # catch, so this only ever blocks a genuine "new release under a
        # deactivated artist" attempt (database-design.md §3.3/§3.4).
        if idol_id is not None:
            idol = db.get(Idol, idol_id)
            return idol is None or idol.is_active
        if group_id is not None:
            group = db.get(Group, group_id)
            return group is None or group.is_active
        return True

    @staticmethod
    def add_album_detail(db: Session, data: AlbumDetailCreate, current_user: Users) -> AlbumDetail:
        if not db.get(Product, data.product_id):
            raise NotFoundError("Product not found")
        if db.get(AlbumDetail, data.product_id):
            raise BadRequestError("This product already has album details")  # already has album_details
        if not AlbumDetailService._artist_active_or_missing(db, data.idol_id, data.group_id):
            raise BadRequestError("Cannot attach a new release to a deactivated idol/group")
        company_id = AlbumDetailService._resolve_company_id(db, data.idol_id, data.group_id)
        if company_id is None:
            raise NotFoundError("Idol or group not found")  # referenced idol/group doesn't exist
        if AlbumDetailService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage album details for their own company's idols/groups")
        db_album = AlbumDetail(**data.model_dump())
        db.add(db_album)
        commit_or_raise(db)  # trg_album_details_exclusive_kind
        db.refresh(db_album)
        return db_album

    @staticmethod
    def get_album_detail(db: Session, product_id: uuid.UUID) -> AlbumDetail | None:
        return db.get(AlbumDetail, product_id)

    @staticmethod
    def get_album_details(db: Session) -> list[AlbumDetail] | Literal[False]:
        result = db.query(AlbumDetail).all()
        if not result:
            return False
        return result

    @staticmethod
    def update_album_detail(db: Session, product_id: uuid.UUID, data: AlbumDetailUpdate, current_user: Users) -> AlbumDetail:
        db_album = db.get(AlbumDetail, product_id)
        if not db_album:
            raise NotFoundError("Album details not found")
        company_id = AlbumDetailService._resolve_company_id(db, db_album.idol_id, db_album.group_id)
        if AlbumDetailService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage album details for their own company's idols/groups")
        db_album.release_date = data.release_date
        db_album.track_count = data.track_count
        db_album.format = data.format
        db_album.cover_image_url = data.cover_image_url
        db.commit()
        db.refresh(db_album)
        return db_album

    @staticmethod
    def delete_album_detail(db: Session, product_id: uuid.UUID, current_user: Users) -> AlbumDetail:
        db_album = db.get(AlbumDetail, product_id)
        if not db_album:
            raise NotFoundError("Album details not found")
        company_id = AlbumDetailService._resolve_company_id(db, db_album.idol_id, db_album.group_id)
        if AlbumDetailService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage album details for their own company's idols/groups")
        db.delete(db_album)
        db.commit()
        return db_album
