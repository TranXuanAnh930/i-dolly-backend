import uuid
from typing import Any, Literal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.models.events import Concert, ConcertPerformer
from app.db.models.identity import Users
from app.db.models.marketplace import Product
from app.db.models.talent import Group, Idol, ManagementCompany
from app.exception.common import ForbiddenError, NotFoundError
from app.schema.talent import GroupCreate, GroupUpdate
from app.services.marketplace.product_service import ProductService
from app.services.talent.idol_service import IdolService


class GroupService:

    # Authorization convention for this module: NotFoundError = a referenced
    # row doesn't exist (-> 404 in the router); ForbiddenError = the row(s)
    # exist but the caller is a manager acting outside their own company_id
    # (-> 403). A plain admin is never scoped — only `role == "manager"`
    # triggers the company check (database-design.md §4: "Not yet done" note,
    # now done for groups/idols).

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == "manager" and current_user.company_id != company_id

    @staticmethod
    def add_group(db: Session, group: GroupCreate, current_user: Users) -> Group:
        if GroupService._manager_scope_violation(current_user, group.company_id):
            raise ForbiddenError("Managers can only manage groups for their own company")
        company = db.get(ManagementCompany, group.company_id)
        if not company:
            raise NotFoundError("Management company not found")  # company_id doesn't exist
        db_group = Group(**group.model_dump())
        db.add(db_group)
        db.commit()
        db.refresh(db_group)
        return db_group

    @staticmethod
    def get_groups(db: Session) -> list[Group] | Literal[False]:
        # Public "browse all groups" list — deactivated groups don't belong on
        # a store-facing listing (database-design.md §3.3).
        result = db.query(Group).filter(Group.is_active.is_(True)).all()
        if not result:
            return False
        return result

    @staticmethod
    def get_group(db: Session, id: uuid.UUID) -> Group | None:
        # Deliberately NOT filtered by is_active: this is the plain by-id lookup
        # behind GET /groups/{id}, which a manager's edit form also needs to be
        # able to load a deactivated group in order to review/reactivate it.
        return db.get(Group, id)

    @staticmethod
    def update_group(db: Session, id: uuid.UUID, data: GroupUpdate, current_user: Users) -> Group:
        db_group = db.get(Group, id)
        if not db_group:
            raise NotFoundError("Group not found")
        if GroupService._manager_scope_violation(current_user, db_group.company_id):
            raise ForbiddenError("Managers can only manage groups for their own company")
        db_group.name = data.name
        db_group.debut_date = data.debut_date
        db_group.description = data.description
        db.commit()
        db.refresh(db_group)
        return db_group

    @staticmethod
    def delete_group(db: Session, id: uuid.UUID, current_user: Users) -> Literal[True]:
        # Soft delete, not db.delete(): concert_performers CASCADEs off
        # groups.id and album_details/merch_details SET NULL their group_id —
        # hard-deleting a group with concert or product history would destroy
        # or orphan that history. Deactivating in place keeps every FK target
        # alive (database-design.md §3.3).
        db_group = db.get(Group, id)
        if not db_group:
            raise NotFoundError("Group not found")
        if GroupService._manager_scope_violation(current_user, db_group.company_id):
            raise ForbiddenError("Managers can only manage groups for their own company")
        db_group.is_active = False
        db.commit()
        return True

    @staticmethod
    def reactivate_group(db: Session, id: uuid.UUID, current_user: Users) -> Group:
        db_group = db.get(Group, id)
        if not db_group:
            raise NotFoundError("Group not found")
        if GroupService._manager_scope_violation(current_user, db_group.company_id):
            raise ForbiddenError("Managers can only manage groups for their own company")
        db_group.is_active = True
        db.commit()
        db.refresh(db_group)
        return db_group

    # --- page-shaped reads (see idol_service.py's equivalent comment) ---

    @staticmethod
    def get_groups_page(db: Session) -> dict[str, Any] | Literal[False]:
        # Store-facing browse page — same is_active filter as get_groups.
        groups = db.query(Group).filter(Group.is_active.is_(True)).all()
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

    @staticmethod
    def get_group_detail(db: Session, id: uuid.UUID) -> dict[str, Any] | Literal[False]:
        # Public group profile page — a deactivated group reads as "not found"
        # here, same as get_groups/get_groups_page; only the manager/admin
        # settings surfaces (get_manager_groups_page, plain get_group) still see it.
        group = db.get(Group, id)
        if not group or not group.is_active:
            return False

        members = (
            db.query(Idol)
            .options(*IdolService._with_positions_and_color())
            .filter(Idol.group_id == id, Idol.is_active.is_(True))
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
            card for card in ProductService._build_product_cards(db, all_products)
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

    @staticmethod
    def get_manager_groups_page(db: Session) -> dict[str, Any]:
        return {"groups": db.query(Group).all()}
