import uuid
from typing import Literal

from sqlalchemy.orm import Session, joinedload

from app.db.models.events import Concert, LotteryCampaign, TicketType
from app.db.models.identity import Users
from app.schema.events import LotteryCampaignCreate, LotteryCampaignUpdate


class LotteryCampaignService:

    # Company-scoped via a two-level join: ticket_type_id -> concert_id ->
    # concert.company_id (database-design.md's dual-FK scoping note).

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID | None) -> bool:
        return current_user.role == "manager" and current_user.company_id != company_id

    @staticmethod
    def _company_id_for_ticket_type(db: Session, ticket_type_id: uuid.UUID) -> uuid.UUID | None:
        tt = db.get(TicketType, ticket_type_id)
        if not tt:
            return None
        concert = db.get(Concert, tt.concert_id)
        return concert.company_id if concert else None

    @staticmethod
    def add_campaign(db: Session, data: LotteryCampaignCreate, current_user: Users) -> LotteryCampaign | Literal["not_found", "not_lottery_ticket_type", "forbidden"]:
        ticket_type = db.get(TicketType, data.ticket_type_id)
        if not ticket_type:
            return "not_found"
        if ticket_type.sale_method != "lottery":
            return "not_lottery_ticket_type"  # a campaign only ever makes sense for a lottery-sale tier
        concert = db.get(Concert, ticket_type.concert_id)
        if not concert:
            return "not_found"
        if LotteryCampaignService._manager_scope_violation(current_user, concert.company_id):
            return "forbidden"
        db_campaign = LotteryCampaign(**data.model_dump())
        db.add(db_campaign)
        db.commit()
        db.refresh(db_campaign)
        return db_campaign

    @staticmethod
    def get_campaigns(db: Session, ticket_type_id: uuid.UUID) -> list[LotteryCampaign] | Literal[False]:
        # joinedload since LotteryCampaignRead now embeds ticket_type — without
        # it, serializing a multi-row result would lazy-load it once per row.
        result = (
            db.query(LotteryCampaign)
            .options(joinedload(LotteryCampaign.ticket_type))
            .filter(LotteryCampaign.ticket_type_id == ticket_type_id)
            .all()
        )
        if not result:
            return False
        return result

    @staticmethod
    def get_campaign(db: Session, id: uuid.UUID) -> LotteryCampaign | None:
        return db.get(LotteryCampaign, id)

    @staticmethod
    def update_campaign(db: Session, id: uuid.UUID, data: LotteryCampaignUpdate, current_user: Users) -> LotteryCampaign | Literal["not_found", "forbidden"]:
        db_campaign = db.get(LotteryCampaign, id)
        if not db_campaign:
            return "not_found"
        company_id = LotteryCampaignService._company_id_for_ticket_type(db, db_campaign.ticket_type_id)
        if LotteryCampaignService._manager_scope_violation(current_user, company_id):
            return "forbidden"
        db_campaign.entry_start_at = data.entry_start_at
        db_campaign.entry_end_at = data.entry_end_at
        db_campaign.payment_deadline_hours = data.payment_deadline_hours
        db_campaign.max_entries_per_user = data.max_entries_per_user
        if data.status is not None:
            db_campaign.status = data.status
        db.commit()
        db.refresh(db_campaign)
        return db_campaign

    @staticmethod
    def delete_campaign(db: Session, id: uuid.UUID, current_user: Users) -> Literal["not_found", "forbidden", True]:
        db_campaign = db.get(LotteryCampaign, id)
        if not db_campaign:
            return "not_found"
        company_id = LotteryCampaignService._company_id_for_ticket_type(db, db_campaign.ticket_type_id)
        if LotteryCampaignService._manager_scope_violation(current_user, company_id):
            return "forbidden"
        db.delete(db_campaign)
        db.commit()
        return True
