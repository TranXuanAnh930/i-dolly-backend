import uuid
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import LotteryPreference
from app.db.models.identity import Users
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.exception.db_triggers import TriggerViolationError
from app.schema.events import LotteryPreferenceRead, LotteryPreferenceSet
from app.services.events.lottery_preference_service import LotteryPreferenceService

# Fan-facing / self-scoped — see lottery_preference_service for rationale.
# Every endpoint operates on current_user's own rows only; there's no
# id-addressed single-row CRUD here on purpose (see LotteryPreferenceSet).
router = APIRouter(prefix="/lottery_preferences", tags=["Lottery Preferences"])

def _raise_for(result: Literal["not_found", "invalid", "not_lottery_ticket_type"]) -> None:
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Concert or ticket type not found, or a ticket type doesn't belong to this concert")
    if result == "invalid":
        raise HTTPException(status_code=400, detail="Duplicate ticket_type_id in the ranked list")
    if result == "not_lottery_ticket_type":
        raise HTTPException(status_code=400, detail="Can only rank lottery-sale ticket types")

@router.post("/set", response_model=List[LotteryPreferenceRead])
async def set_my_preferences(data: LotteryPreferenceSet, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(10, 60, user_key)), db: Session = Depends(get_db)) -> list[LotteryPreference]:
    try:
        result = LotteryPreferenceService.set_preferences(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if isinstance(result, str):
        _raise_for(result)
    return result

@router.get("/mine/{concert_id}", response_model=List[LotteryPreferenceRead])
async def list_my_preferences(concert_id: uuid.UUID, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(15, 60, user_key)), db: Session = Depends(get_db)) -> list[LotteryPreference]:
    result = LotteryPreferenceService.get_my_preferences(db, concert_id, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no preferences set for this concert")
    return result

@router.delete("/mine/{concert_id}")
async def delete_my_preferences(concert_id: uuid.UUID, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(10, 60, user_key)), db: Session = Depends(get_db)) -> dict[str, str]:
    result = LotteryPreferenceService.clear_my_preferences(db, concert_id, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no preferences set for this concert")
    return {"msg": "Preferences cleared successfully"}
