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
from app.schema.events import LotteryDrawResultRead, LotteryEntryApply, LotteryEntryApplyBatch, LotteryEntryRead
from app.services.events.lottery_entry_service import LotteryEntryService

router = APIRouter(prefix="/lottery_entries", tags=["Lottery Entries"])

# Not used by the frontend, which submits every tier through /apply-batch.
@router.post("/apply", response_model=LotteryEntryRead)
def apply_to_a_lottery(data: LotteryEntryApply, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> LotteryEntry:
    try:
        return LotteryEntryService.apply_to_lottery(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Applies to several tiers in one request, using one rate-limit slot (3 per 60s, same as /apply).
@router.post("/apply-batch", response_model=List[LotteryEntryRead])
def apply_to_lotteries(data: LotteryEntryApplyBatch, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db: Session = Depends(get_db)) -> list[LotteryEntry]:
    try:
        return LotteryEntryService.apply_to_lotteries(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.get("/mine", response_model=List[LotteryEntryRead])
def list_my_entries(current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)) -> list[LotteryEntry]:
    result = LotteryEntryService.get_my_entries(db, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no lottery entries")
    return result

@router.get("/campaign/{campaign_id}", response_model=List[LotteryEntryRead])
def list_campaign_entries(campaign_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> list[LotteryEntry]:
    try:
        result = LotteryEntryService.get_entries_for_campaign(db, campaign_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if not result:
        raise HTTPException(status_code=404, detail="No entries found for this campaign")
    return result

# Won and lost entries across every campaign of a concert, each with the winner's email and ticket
# payment status.
@router.get("/concert/{concert_id}/results", response_model=List[LotteryDrawResultRead])
def list_concert_draw_results(concert_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)) -> list[LotteryDrawResultRead]:
    try:
        result = LotteryEntryService.get_draw_results_for_concert(db, concert_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if not result:
        raise HTTPException(status_code=404, detail="No lottery results found for this concert")
    return result
