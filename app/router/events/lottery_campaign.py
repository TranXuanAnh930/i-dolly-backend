import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import LotteryCampaign
from app.db.models.identity import Users
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.events import LotteryCampaignCreate, LotteryCampaignRead, LotteryCampaignUpdate
from app.services.events.lottery_campaign_service import LotteryCampaignService
from app.services.events.ticket_type_service import TicketTypeService

router = APIRouter(prefix="/lottery_campaigns", tags=["Lottery Campaigns"])

# A campaign's own row has no concert_id column — it's reached via
# ticket_type_id -> ticket_type.concert_id (same two-level scoping
# lottery_campaign_service._company_id_for_ticket_type uses for company
# scoping). Resolved here through the existing TicketTypeService read
# rather than a fresh query, so this stays a service call, not an
# ORM query in the router.
def _concert_id_for(db: Session, ticket_type_id: uuid.UUID) -> uuid.UUID | None:
    ticket_type = TicketTypeService.get_ticket_type(db, ticket_type_id)
    return ticket_type.concert_id if ticket_type else None

@router.post("/add", response_model=LotteryCampaignRead)
async def add_new_campaign(data: LotteryCampaignCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> LotteryCampaign:
    try:
        result = LotteryCampaignService.add_campaign(db, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    concert_id = _concert_id_for(db, result.ticket_type_id)
    if concert_id:
        CacheService.delete_cached_concert_detail(concert_id)
    return result

@router.get("/ticket_type/{ticket_type_id}", response_model=List[LotteryCampaignRead])
async def list_campaigns(ticket_type_id: uuid.UUID, db: Session = Depends(get_db)) -> list[LotteryCampaign]:
    result = LotteryCampaignService.get_campaigns(db, ticket_type_id)
    if not result:
        raise HTTPException(status_code=404, detail="No lottery campaigns found for this ticket type")
    return result

@router.get("/{id}", response_model=LotteryCampaignRead)
async def get_campaign_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> LotteryCampaign:
    campaign = LotteryCampaignService.get_campaign(db, id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Lottery campaign not found")
    return campaign

@router.put("/update/{id}", response_model=LotteryCampaignRead)
async def update_existing_campaign(id: uuid.UUID, data: LotteryCampaignUpdate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> LotteryCampaign:
    try:
        result = LotteryCampaignService.update_campaign(db, id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    concert_id = _concert_id_for(db, result.ticket_type_id)
    if concert_id:
        CacheService.delete_cached_concert_detail(concert_id)
    return result

@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_campaign(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        result = LotteryCampaignService.delete_campaign(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    concert_id = _concert_id_for(db, result.ticket_type_id)
    if concert_id:
        CacheService.delete_cached_concert_detail(concert_id)
    return MessageResponse(msg="Lottery campaign deleted successfully")
