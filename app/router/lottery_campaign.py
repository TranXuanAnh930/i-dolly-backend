import uuid
from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.lottery_campaign import LotteryCampaignCreate, LotteryCampaignUpdate, LotteryCampaignRead
from app.services.lottery_campaign_service import (
    add_campaign, get_campaigns, get_campaign, update_campaign, delete_campaign,
)

router = APIRouter(prefix="/lottery_campaigns", tags=["Lottery Campaigns"])

def _raise_for(result, not_found_detail: str):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage lottery campaigns for their own company's concerts")
    if result == "not_found":
        raise HTTPException(status_code=404, detail=not_found_detail)

@router.post("/add", response_model=LotteryCampaignRead)
async def add_new_campaign(data: LotteryCampaignCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = add_campaign(db, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Ticket type not found")
    return result

@router.get("/ticket_type/{ticket_type_id}", response_model=List[LotteryCampaignRead])
async def list_campaigns(ticket_type_id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_campaigns(db, ticket_type_id)
    if not result:
        raise HTTPException(status_code=404, detail="No lottery campaigns found for this ticket type")
    return result

@router.get("/{id}", response_model=LotteryCampaignRead)
async def get_campaign_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    campaign = get_campaign(db, id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Lottery campaign not found")
    return campaign

@router.put("/update/{id}", response_model=LotteryCampaignRead)
async def update_existing_campaign(id: uuid.UUID, data: LotteryCampaignUpdate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = update_campaign(db, id, data, current_user)
    if isinstance(result, str):
        _raise_for(result, "Lottery campaign not found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_campaign(id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = delete_campaign(db, id, current_user)
    if isinstance(result, str):
        _raise_for(result, "Lottery campaign not found")
    return {"msg": "Lottery campaign deleted successfully"}
