import uuid

from sqlalchemy.orm import Session

from app.db.models.events import Concert, DirectSaleCampaign, TicketType
from app.db.models.identity import Users
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.schema.events import DirectSaleCampaignCreate, DirectSaleCampaignUpdate
from app.schema.events.ticket_type import SaleMethod
from app.schema.identity import UserRole


class DirectSaleCampaignService:

    # Company-scoped via ticket_type -> concert.company_id.

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID | None) -> bool:
        return current_user.role == UserRole.manager and current_user.company_id != company_id

    @staticmethod
    def add_campaign(db: Session, data: DirectSaleCampaignCreate, current_user: Users) -> DirectSaleCampaign:
        ticket_type = db.get(TicketType, data.ticket_type_id)
        if not ticket_type:
            raise NotFoundError("Ticket type not found")
        if ticket_type.sale_method != SaleMethod.direct:
            raise BadRequestError("Direct sale campaigns can only be attached to a direct-sale ticket type")
        concert = db.get(Concert, ticket_type.concert_id)
        if not concert:
            raise NotFoundError("Concert not found")
        if DirectSaleCampaignService._manager_scope_violation(current_user, concert.company_id):
            raise ForbiddenError("Managers can only manage direct sale campaigns for their own company's concerts")
        db_campaign = DirectSaleCampaign(**data.model_dump())
        db.add(db_campaign)
        db.commit()
        db.refresh(db_campaign)
        return db_campaign

    @staticmethod
    def get_campaigns(db: Session, ticket_type_id: uuid.UUID) -> list[DirectSaleCampaign]:
        return db.query(DirectSaleCampaign).filter(DirectSaleCampaign.ticket_type_id == ticket_type_id).all()

    @staticmethod
    def get_campaign(db: Session, id: uuid.UUID) -> DirectSaleCampaign | None:
        return db.get(DirectSaleCampaign, id)

    @staticmethod
    def _company_id_for_campaign(db: Session, db_campaign: DirectSaleCampaign) -> uuid.UUID | None:
        ticket_type = db.get(TicketType, db_campaign.ticket_type_id)
        if not ticket_type:
            return None
        concert = db.get(Concert, ticket_type.concert_id)
        return concert.company_id if concert else None

    @staticmethod
    def update_campaign(db: Session, id: uuid.UUID, data: DirectSaleCampaignUpdate, current_user: Users) -> DirectSaleCampaign:
        db_campaign = db.get(DirectSaleCampaign, id)
        if not db_campaign:
            raise NotFoundError("Direct sale campaign not found")
        company_id = DirectSaleCampaignService._company_id_for_campaign(db, db_campaign)
        if DirectSaleCampaignService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage direct sale campaigns for their own company's concerts")
        db_campaign.sale_start_at = data.sale_start_at
        db_campaign.sale_end_at = data.sale_end_at
        if data.status is not None:
            db_campaign.status = data.status
        db.commit()
        db.refresh(db_campaign)
        return db_campaign

    @staticmethod
    def delete_campaign(db: Session, id: uuid.UUID, current_user: Users) -> DirectSaleCampaign:
        db_campaign = db.get(DirectSaleCampaign, id)
        if not db_campaign:
            raise NotFoundError("Direct sale campaign not found")
        company_id = DirectSaleCampaignService._company_id_for_campaign(db, db_campaign)
        if DirectSaleCampaignService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only manage direct sale campaigns for their own company's concerts")
        db.delete(db_campaign)
        db.commit()
        return db_campaign
