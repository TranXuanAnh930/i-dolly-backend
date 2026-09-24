import uuid

from sqlalchemy.orm import Session, joinedload

from app.db.models.events import Concert, LotteryCampaign, TicketType
from app.db.models.identity import Users
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.schema.events import LotteryCampaignCreate, LotteryCampaignUpdate
from app.schema.events.ticket_type import SaleMethod
from app.schema.identity import UserRole


class LotteryCampaignService:

    # Company-scoped via a two-level join: ticket_type_id -> concert_id ->
    # concert.company_id (database-design.md's dual-FK scoping note).

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID | None) -> bool:
        return current_user.role == UserRole.manager and current_user.company_id != company_id

    @staticmethod
    def _company_id_for_ticket_type(db: Session, ticket_type_id: uuid.UUID) -> uuid.UUID | None:
        tt = db.get(TicketType, ticket_type_id)
        if not tt:
            return None
        concert = db.get(Concert, tt.concert_id)
        return concert.company_id if concert else None

    @staticmethod
    def add_campaign(db: Session, data: LotteryCampaignCreate, current_user: Users) -> LotteryCampaign:
        ticket_type = db.get(TicketType, data.ticket_type_id)
        if not ticket_type:
            raise NotFoundError("Ticket type not found")
        if ticket_type.sale_method != SaleMethod.lottery:
            raise BadRequestError("Lottery campaigns can only be attached to a lottery-sale ticket type")
        concert = db.get(Concert, ticket_type.concert_id)
        if not concert:
            raise NotFoundError("Concert not found")
        if LotteryCampaignService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage lottery campaigns for their own company's concerts")
        db_campaign = LotteryCampaign(**data.model_dump())
        db.add(db_campaign)
        db.commit()
        db.refresh(db_campaign)
        return db_campaign

    @staticmethod
    def get_campaigns(db: Session, ticket_type_id: uuid.UUID) -> list[LotteryCampaign]:
        # joinedload since LotteryCampaignRead now embeds ticket_type — without
        # it, serializing a multi-row result would lazy-load it once per row.
        return (
            db.query(LotteryCampaign)
            .options(joinedload(LotteryCampaign.ticket_type))
            .filter(LotteryCampaign.ticket_type_id == ticket_type_id)
            .all()
        )

    @staticmethod
    def get_campaign(db: Session, id: uuid.UUID) -> LotteryCampaign | None:
        return db.get(LotteryCampaign, id)

    @staticmethod
    def update_campaign(db: Session, id: uuid.UUID, data: LotteryCampaignUpdate, current_user: Users) -> LotteryCampaign:
        db_campaign = db.get(LotteryCampaign, id)
        if not db_campaign:
            raise NotFoundError("Lottery campaign not found")
        company_id = LotteryCampaignService._company_id_for_ticket_type(db, db_campaign.ticket_type_id)
        if LotteryCampaignService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage lottery campaigns for their own company's concerts")
        db_campaign.entry_start_at = data.entry_start_at
        db_campaign.entry_end_at = data.entry_end_at
        db_campaign.payment_deadline_hours = data.payment_deadline_hours
        if data.status is not None:
            db_campaign.status = data.status
        db.commit()
        db.refresh(db_campaign)
        return db_campaign

    @staticmethod
    def delete_campaign(db: Session, id: uuid.UUID, current_user: Users) -> LotteryCampaign:
        db_campaign = db.get(LotteryCampaign, id)
        if not db_campaign:
            raise NotFoundError("Lottery campaign not found")
        company_id = LotteryCampaignService._company_id_for_ticket_type(db, db_campaign.ticket_type_id)
        if LotteryCampaignService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage lottery campaigns for their own company's concerts")
        db.delete(db_campaign)
        db.commit()
        return db_campaign
