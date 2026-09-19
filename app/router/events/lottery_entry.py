import uuid
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import LotteryEntry
from app.db.models.identity import Users
from app.deps.auth import get_current_user, require_manager_or_admin
from app.deps.db import get_db
from app.exception.db_triggers import TriggerViolationError
from app.schema.events import LotteryEntryApply, LotteryEntryRead
from app.services.events.lottery_entry_service import LotteryEntryService

router = APIRouter(prefix="/lottery_entries", tags=["Lottery Entries"])

def _raise_for(result: Literal["fan_only", "forbidden", "not_found", "no_preference", "cap_reached", "already_has_ticket"]) -> None:
    if result == "fan_only":
        raise HTTPException(status_code=403, detail="Only fan accounts can apply to a lottery")
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only view entries for their own company's campaigns")
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Lottery campaign not found")
    if result == "no_preference":
        raise HTTPException(status_code=400, detail="Rank this ticket tier in your lottery preferences before applying")
    if result == "cap_reached":
        raise HTTPException(status_code=400, detail="You've already used all your entries for this campaign")
    if result == "already_has_ticket":
        raise HTTPException(status_code=400, detail="You already hold a ticket for this concert")

@router.post("/apply", response_model=LotteryEntryRead)
async def apply_to_a_lottery(data: LotteryEntryApply, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> LotteryEntry:
    try:
        result = LotteryEntryService.apply_to_lottery(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if isinstance(result, str):
        _raise_for(result)
    return result

@router.get("/mine", response_model=List[LotteryEntryRead])
async def list_my_entries(current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)) -> list[LotteryEntry]:
    result = LotteryEntryService.get_my_entries(db, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no lottery entries")
    return result

@router.get("/campaign/{campaign_id}", response_model=List[LotteryEntryRead])
async def list_campaign_entries(campaign_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> list[LotteryEntry]:
    result = LotteryEntryService.get_entries_for_campaign(db, campaign_id, current_user)
    if isinstance(result, str):
        _raise_for(result)
    if not result:
        raise HTTPException(status_code=404, detail="No entries found for this campaign")
    return result
