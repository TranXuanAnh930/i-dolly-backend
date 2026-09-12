import uuid
from sqlalchemy.orm import Session
from app.schema.direct_sale_campaign import DirectSaleCampaignCreate, DirectSaleCampaignUpdate
from app.db.models.direct_sale_campaign import DirectSaleCampaign
from app.db.models.ticket_type import TicketType
from app.db.models.concert import Concert
from app.db.models.user import Users

# Company-scoped via a two-level join: ticket_type_id -> concert_id ->
# concert.company_id — same pattern as lottery_campaign_service.

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def add_campaign(db: Session, data: DirectSaleCampaignCreate, current_user: Users):
    ticket_type = db.get(TicketType, data.ticket_type_id)
    if not ticket_type:
        return "not_found"
    if ticket_type.sale_method != "direct":
        return "not_direct_sale_ticket_type"  # a campaign only ever makes sense for a direct-sale tier
    concert = db.get(Concert, ticket_type.concert_id)
    if not concert:
        return "not_found"
    if _manager_scope_violation(current_user, concert.company_id):
        return "forbidden"
    db_campaign = DirectSaleCampaign(**data.model_dump())
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return db_campaign

def get_campaigns(db: Session, ticket_type_id: uuid.UUID):
    result = db.query(DirectSaleCampaign).filter(DirectSaleCampaign.ticket_type_id == ticket_type_id).all()
    if not result:
        return False
    return result

def get_campaign(db: Session, id: uuid.UUID):
    return db.get(DirectSaleCampaign, id)

def _company_id_for_campaign(db: Session, db_campaign: DirectSaleCampaign):
    ticket_type = db.get(TicketType, db_campaign.ticket_type_id)
    if not ticket_type:
        return None
    concert = db.get(Concert, ticket_type.concert_id)
    return concert.company_id if concert else None

def update_campaign(db: Session, id: uuid.UUID, data: DirectSaleCampaignUpdate, current_user: Users):
    db_campaign = db.get(DirectSaleCampaign, id)
    if not db_campaign:
        return "not_found"
    company_id = _company_id_for_campaign(db, db_campaign)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db_campaign.sale_start_at = data.sale_start_at
    db_campaign.sale_end_at = data.sale_end_at
    if data.status is not None:
        db_campaign.status = data.status
    db.commit()
    db.refresh(db_campaign)
    return db_campaign

def delete_campaign(db: Session, id: uuid.UUID, current_user: Users):
    db_campaign = db.get(DirectSaleCampaign, id)
    if not db_campaign:
        return "not_found"
    company_id = _company_id_for_campaign(db, db_campaign)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db.delete(db_campaign)
    db.commit()
    return True
