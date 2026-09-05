from sqlalchemy.orm import Session
from app.schema.lottery_campaign import LotteryCampaignCreate, LotteryCampaignUpdate
from app.db.models.lottery_campaign import LotteryCampaign
from app.db.models.ticket_type import TicketType
from app.db.models.concert import Concert
from app.db.models.user import Users

# Company-scoped via a two-level join: ticket_type_id -> concert_id ->
# concert.company_id (database-design.md's dual-FK scoping note).

def _manager_scope_violation(current_user: Users, company_id: int) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def _company_id_for_ticket_type(db: Session, ticket_type_id: int):
    tt = db.get(TicketType, ticket_type_id)
    if not tt:
        return None
    concert = db.get(Concert, tt.concert_id)
    return concert.company_id if concert else None

def add_campaign(db: Session, data: LotteryCampaignCreate, current_user: Users):
    company_id = _company_id_for_ticket_type(db, data.ticket_type_id)
    if company_id is None:
        return "not_found"
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db_campaign = LotteryCampaign(**data.model_dump())
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return db_campaign

def get_campaigns(db: Session, ticket_type_id: int):
    result = db.query(LotteryCampaign).filter(LotteryCampaign.ticket_type_id == ticket_type_id).all()
    if not result:
        return False
    return result

def get_campaign(db: Session, id: int):
    return db.get(LotteryCampaign, id)

def update_campaign(db: Session, id: int, data: LotteryCampaignUpdate, current_user: Users):
    db_campaign = db.get(LotteryCampaign, id)
    if not db_campaign:
        return "not_found"
    company_id = _company_id_for_ticket_type(db, db_campaign.ticket_type_id)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db_campaign.entry_start_at = data.entry_start_at
    db_campaign.entry_end_at = data.entry_end_at
    db_campaign.draw_at = data.draw_at
    db_campaign.payment_deadline_hours = data.payment_deadline_hours
    db_campaign.max_entries_per_user = data.max_entries_per_user
    if data.status is not None:
        db_campaign.status = data.status
    db.commit()
    db.refresh(db_campaign)
    return db_campaign

def delete_campaign(db: Session, id: int, current_user: Users):
    db_campaign = db.get(LotteryCampaign, id)
    if not db_campaign:
        return "not_found"
    company_id = _company_id_for_ticket_type(db, db_campaign.ticket_type_id)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db.delete(db_campaign)
    db.commit()
    return True
