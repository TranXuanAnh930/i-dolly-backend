import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.events import LotteryPreference
from app.db.models.identity import Users
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.exception.db_triggers import TriggerViolationError
from app.schema.events import LotteryPreferenceRead, LotteryPreferenceSet
from app.services.events.lottery_preference_service import LotteryPreferenceService

# Fan-facing / self-scoped — see lottery_preference_service for rationale.
# Every endpoint operates on current_user's own rows only; there's no
# id-addressed single-row CRUD here on purpose (see LotteryPreferenceSet).
router = APIRouter(prefix="/lottery_preferences", tags=["Lottery Preferences"])

@router.post("/set", response_model=List[LotteryPreferenceRead])
async def set_my_preferences(data: LotteryPreferenceSet, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(10, 60, user_key)), db: Session = Depends(get_db)) -> list[LotteryPreference]:
    try:
        return LotteryPreferenceService.set_preferences(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

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
