import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import LotteryEntry
from app.db.models.identity import Users
from app.deps.auth import get_current_user, require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.exception.db_triggers import TriggerViolationError
from app.schema.events import LotteryEntryApply, LotteryEntryRead
from app.services.events.lottery_entry_service import LotteryEntryService

router = APIRouter(prefix="/lottery_entries", tags=["Lottery Entries"])

@router.post("/apply", response_model=LotteryEntryRead)
async def apply_to_a_lottery(data: LotteryEntryApply, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> LotteryEntry:
    try:
        return LotteryEntryService.apply_to_lottery(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.get("/mine", response_model=List[LotteryEntryRead])
async def list_my_entries(current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)) -> list[LotteryEntry]:
    result = LotteryEntryService.get_my_entries(db, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no lottery entries")
    return result

@router.get("/campaign/{campaign_id}", response_model=List[LotteryEntryRead])
async def list_campaign_entries(campaign_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> list[LotteryEntry]:
    try:
        result = LotteryEntryService.get_entries_for_campaign(db, campaign_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if not result:
        raise HTTPException(status_code=404, detail="No entries found for this campaign")
    return result
