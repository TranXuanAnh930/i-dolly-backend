import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import DirectSaleCampaign
from app.db.models.identity import Users
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.events import DirectSaleCampaignCreate, DirectSaleCampaignRead, DirectSaleCampaignUpdate
from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService
from app.services.events.ticket_type_service import TicketTypeService

router = APIRouter(prefix="/direct_sale_campaigns", tags=["Direct Sale Campaigns"])

# A campaign's own row has no concert_id column — it's reached via
# ticket_type_id -> ticket_type.concert_id, resolved here through the
# existing TicketTypeService read rather than a fresh ORM query in the
# router (mirrors lottery_campaign.py's identical helper).
def _concert_id_for(db: Session, ticket_type_id: uuid.UUID) -> uuid.UUID | None:
    ticket_type = TicketTypeService.get_ticket_type(db, ticket_type_id)
    return ticket_type.concert_id if ticket_type else None

@router.post("/add", response_model=DirectSaleCampaignRead)
async def add_new_campaign(data: DirectSaleCampaignCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> DirectSaleCampaign:
    try:
        result = DirectSaleCampaignService.add_campaign(db, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    concert_id = _concert_id_for(db, result.ticket_type_id)
    if concert_id:
        CacheService.delete_cached_concert_detail(concert_id)
    return result

@router.get("/ticket_type/{ticket_type_id}", response_model=List[DirectSaleCampaignRead])
async def list_campaigns(ticket_type_id: uuid.UUID, db: Session = Depends(get_db)) -> list[DirectSaleCampaign]:
    result = DirectSaleCampaignService.get_campaigns(db, ticket_type_id)
    if not result:
        raise HTTPException(status_code=404, detail="No direct sale campaigns found for this ticket type")
    return result

@router.get("/{id}", response_model=DirectSaleCampaignRead)
async def get_campaign_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> DirectSaleCampaign:
    campaign = DirectSaleCampaignService.get_campaign(db, id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Direct sale campaign not found")
    return campaign

@router.put("/update/{id}", response_model=DirectSaleCampaignRead)
async def update_existing_campaign(id: uuid.UUID, data: DirectSaleCampaignUpdate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> DirectSaleCampaign:
    try:
        result = DirectSaleCampaignService.update_campaign(db, id, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    concert_id = _concert_id_for(db, result.ticket_type_id)
    if concert_id:
        CacheService.delete_cached_concert_detail(concert_id)
    return result

@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_campaign(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        result = DirectSaleCampaignService.delete_campaign(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    concert_id = _concert_id_for(db, result.ticket_type_id)
    if concert_id:
        CacheService.delete_cached_concert_detail(concert_id)
    return MessageResponse(msg="Direct sale campaign deleted successfully")
