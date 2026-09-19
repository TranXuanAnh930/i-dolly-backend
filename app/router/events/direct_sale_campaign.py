import uuid
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import DirectSaleCampaign
from app.db.models.identity import Users
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.schema.events import DirectSaleCampaignCreate, DirectSaleCampaignRead, DirectSaleCampaignUpdate
from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

router = APIRouter(prefix="/direct_sale_campaigns", tags=["Direct Sale Campaigns"])

def _raise_for(result: Literal["forbidden", "not_found", "not_direct_sale_ticket_type"], not_found_detail: str) -> None:
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage direct sale campaigns for their own company's concerts")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "not_direct_sale_ticket_type":
        raise HTTPException(status_code=400, detail="Direct sale campaigns can only be attached to a direct-sale ticket type")

@router.post("/add", response_model=DirectSaleCampaignRead)
async def add_new_campaign(data: DirectSaleCampaignCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> DirectSaleCampaign:
    result = DirectSaleCampaignService.add_campaign(db, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Ticket type not found")
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
    result = DirectSaleCampaignService.update_campaign(db, id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Direct sale campaign not found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_campaign(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> dict[str, str]:
    result = DirectSaleCampaignService.delete_campaign(db, id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Direct sale campaign not found")
    return {"msg": "Direct sale campaign deleted successfully"}
