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
from app.schema.events import LotteryEntryApply, LotteryEntryApplyBatch, LotteryEntryRead
from app.services.events.lottery_entry_service import LotteryEntryService

router = APIRouter(prefix="/lottery_entries", tags=["Lottery Entries"])

# FRONTEND: not currently called by i-dolly-frontend — LotteryEntryPage submits
# every tier at once through /apply-batch below, for the rate-limit reason
# documented there. Kept as the single-entry API in its own right.
@router.post("/apply", response_model=LotteryEntryRead)
async def apply_to_a_lottery(data: LotteryEntryApply, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> LotteryEntry:
    try:
        return LotteryEntryService.apply_to_lottery(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# One submission = one request = one rate-limit slot, deliberately the same
# 3/60s budget as a single apply. A client entering several of a concert's tiers
# should come here rather than looping /apply: that loop spends a slot per tier,
# so a fan ranking 4+ tiers would have the tail of their submission 429'd with
# the earlier tiers already committed.
@router.post("/apply-batch", response_model=List[LotteryEntryRead])
async def apply_to_lotteries(data: LotteryEntryApplyBatch, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> list[LotteryEntry]:
    try:
        return LotteryEntryService.apply_to_lotteries(db, data, current_user)
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
