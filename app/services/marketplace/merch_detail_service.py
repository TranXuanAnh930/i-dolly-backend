import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models.identity import Users
from app.db.models.marketplace import MerchDetail, Product
from app.db.models.talent import Group, Idol, IdolColor
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import commit_or_raise
from app.schema.marketplace import MerchDetailCreate, MerchDetailUpdate


class MerchDetailService:

    # Same dual-FK scoping as album_details.

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
        # Same rule as album_detail_service's equivalent helper.
        if idol_id is not None:
            idol = db.get(Idol, idol_id)
            return idol is None or idol.is_active
        if group_id is not None:
            group = db.get(Group, group_id)
            return group is None or group.is_active
        return True

    @staticmethod
    def add_merch_detail(db: Session, data: MerchDetailCreate, current_user: Users) -> MerchDetail:
        if not db.get(Product, data.product_id):
            raise NotFoundError("Product not found")
        if db.get(MerchDetail, data.product_id):
            raise BadRequestError("This product already has merch details")
        if data.color_id is not None and not db.get(IdolColor, data.color_id):
            raise NotFoundError("Idol color not found")
        if not MerchDetailService._artist_active_or_missing(db, data.idol_id, data.group_id):
            raise BadRequestError("Cannot attach new merch to a deactivated idol/group")
        company_id = MerchDetailService._resolve_company_id(db, data.idol_id, data.group_id)
        if company_id is None:
            raise NotFoundError("Idol or group not found")
        if MerchDetailService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage merch details for their own company's idols/groups")
        db_ls = MerchDetail(**data.model_dump())
        db.add(db_ls)
        commit_or_raise(db)  # trg_merch_details_exclusive_kind
        db.refresh(db_ls)
        return db_ls

    @staticmethod
    def get_merch_detail(db: Session, product_id: uuid.UUID) -> MerchDetail | None:
        return db.get(MerchDetail, product_id)

    @staticmethod
    def get_merch_details(db: Session) -> list[MerchDetail] | Literal[False]:
        result = db.query(MerchDetail).all()
        if not result:
            return False
        return result

    @staticmethod
    def update_merch_detail(db: Session, product_id: uuid.UUID, data: MerchDetailUpdate, current_user: Users) -> MerchDetail:
        db_ls = db.get(MerchDetail, product_id)
        if not db_ls:
            raise NotFoundError("Merch details not found")
        company_id = MerchDetailService._resolve_company_id(db, db_ls.idol_id, db_ls.group_id)
        if MerchDetailService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage merch details for their own company's idols/groups")
        if data.color_id is not None and not db.get(IdolColor, data.color_id):
            raise NotFoundError("Idol color not found")
        db_ls.edition = data.edition
        db_ls.color_id = data.color_id
        db.commit()
        db.refresh(db_ls)
        return db_ls

    @staticmethod
    def delete_merch_detail(db: Session, product_id: uuid.UUID, current_user: Users) -> Literal[True]:
        db_ls = db.get(MerchDetail, product_id)
        if not db_ls:
            raise NotFoundError("Merch details not found")
        company_id = MerchDetailService._resolve_company_id(db, db_ls.idol_id, db_ls.group_id)
        if MerchDetailService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage merch details for their own company's idols/groups")
        db.delete(db_ls)
        db.commit()
        return True
