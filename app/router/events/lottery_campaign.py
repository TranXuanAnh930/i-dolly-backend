import uuid
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import LotteryCampaign
from app.db.models.identity import Users
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.schema.events import LotteryCampaignCreate, LotteryCampaignRead, LotteryCampaignUpdate
from app.services.events.lottery_campaign_service import LotteryCampaignService

router = APIRouter(prefix="/lottery_campaigns", tags=["Lottery Campaigns"])

def _raise_for(result: Literal["forbidden", "not_found", "not_lottery_ticket_type"], not_found_detail: str) -> None:
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage lottery campaigns for their own company's concerts")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)
    if result == "not_lottery_ticket_type":
        raise HTTPException(status_code=400, detail="Lottery campaigns can only be attached to a lottery-sale ticket type")

@router.post("/add", response_model=LotteryCampaignRead)
async def add_new_campaign(data: LotteryCampaignCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> LotteryCampaign:
    result = LotteryCampaignService.add_campaign(db, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Ticket type not found")
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
    result = LotteryCampaignService.update_campaign(db, id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Lottery campaign not found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_campaign(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> dict[str, str]:
    result = LotteryCampaignService.delete_campaign(db, id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Lottery campaign not found")
    return {"msg": "Lottery campaign deleted successfully"}
