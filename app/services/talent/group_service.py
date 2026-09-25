import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.models.events import Concert, ConcertPerformer
from app.db.models.identity import Users
from app.db.models.marketplace import Product
from app.db.models.talent import Group, Idol, ManagementCompany
from app.exception.common import ForbiddenError, NotFoundError
from app.schema.identity import UserRole
from app.schema.talent import GroupCreate, GroupDetailRead, GroupsPageRead, GroupUpdate, ManagerGroupsPageRead
from app.services.marketplace.product_service import ProductService
from app.services.talent.idol_service import IdolService


class GroupService:

    # Raises NotFoundError for a missing referenced row and ForbiddenError when a manager acts
    # outside their own company. Admins are never company-scoped.

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
        return current_user.role == UserRole.manager and current_user.company_id != company_id

    @staticmethod
    def add_group(db: Session, group: GroupCreate, current_user: Users) -> Group:
        if GroupService._manager_scope_violation(current_user, group.company_id):
            raise ForbiddenError("Managers can only manage groups for their own company")
        company = db.get(ManagementCompany, group.company_id)
        if not company:
            raise NotFoundError("Management company not found")
        db_group = Group(**group.model_dump())
        db.add(db_group)
        db.commit()
        db.refresh(db_group)
        return db_group

    @staticmethod
    def get_groups(db: Session) -> list[Group]:
        # Public list: active groups only.
        return db.query(Group).filter(Group.is_active.is_(True)).all()

    @staticmethod
    def get_group(db: Session, id: uuid.UUID) -> Group | None:
        # Not filtered by is_active, so manager forms can load deactivated groups.
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
    def delete_group(db: Session, id: uuid.UUID, current_user: Users) -> Group:
        # Soft delete: concert and product history references the group.
        db_group = db.get(Group, id)
        if not db_group:
            raise NotFoundError("Group not found")
        if GroupService._manager_scope_violation(current_user, db_group.company_id):
            raise ForbiddenError("Managers can only manage groups for their own company")
        db_group.is_active = False
        db.commit()
        return db_group

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

    # --- page-shaped reads ---

    @staticmethod
    def get_groups_page(db: Session) -> GroupsPageRead | None:
        # Active groups only.
        groups = db.query(Group).filter(Group.is_active.is_(True)).all()
        if not groups:
            return None
        counts = dict(
            db.query(Idol.group_id, func.count(Idol.id))
            .filter(Idol.group_id.isnot(None))
            .group_by(Idol.group_id)
            .all()
        )
        for group in groups:
            group.member_count = counts.get(group.id, 0)
        return GroupsPageRead(groups=groups)

    @staticmethod
    def get_group_detail(db: Session, id: uuid.UUID) -> GroupDetailRead | None:
        # Public profile: a deactivated group is treated as not found.
        group = db.get(Group, id)
        if not group or not group.is_active:
            return None

        members = (
            db.query(Idol)
            .options(*IdolService._with_positions_and_color())
            .filter(Idol.group_id == id, Idol.is_active.is_(True))
            .all()
        )

        # Concerts where the group has a performer credit.
        events = (
            db.query(Concert)
            .join(ConcertPerformer, ConcertPerformer.concert_id == Concert.id)
            .filter(ConcertPerformer.group_id == id)
            .options(joinedload(Concert.venue))
            .distinct()
            .order_by(Concert.event_datetime)
            .all()
        )

        # Products whose resolved artist is this group, including plain merch matched by name
        # (see _build_product_cards).
        all_products = db.query(Product).options(joinedload(Product.category)).all()
        products = [
            card for card in ProductService._build_product_cards(db, all_products)
            if card.artist and card.artist.type == "group" and card.artist.id == id
        ]

        return GroupDetailRead(
            group=group,
            members=members,
            events=events,
            products=products,
        )

    # --- manager/admin settings page (an empty list is a normal result, not a 404)

    @staticmethod
    def get_manager_groups_page(db: Session) -> ManagerGroupsPageRead:
        return ManagerGroupsPageRead(groups=db.query(Group).all())
