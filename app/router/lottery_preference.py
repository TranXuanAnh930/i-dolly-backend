from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.lottery_preference import LotteryPreferenceSet, LotteryPreferenceRead
from app.services.lottery_preference_service import set_preferences, get_my_preferences, clear_my_preferences
from app.exception.db_triggers import TriggerViolationError

# Fan-facing / self-scoped — see lottery_preference_service for rationale.
# Every endpoint operates on current_user's own rows only; there's no
# id-addressed single-row CRUD here on purpose (see LotteryPreferenceSet).
router = APIRouter(prefix="/lottery_preferences", tags=["Lottery Preferences"])

def _raise_for(result):
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Concert or ticket type not found, or a ticket type doesn't belong to this concert")
    if result == "invalid":
        raise HTTPException(status_code=400, detail="Duplicate ticket_type_id in the ranked list")

@router.post("/set", response_model=List[LotteryPreferenceRead])
async def set_my_preferences(data: LotteryPreferenceSet, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = set_preferences(db, data, current_user)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    if isinstance(result, str):
        _raise_for(result)
    return result

@router.get("/mine/{concert_id}", response_model=List[LotteryPreferenceRead])
async def list_my_preferences(concert_id: int, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    result = get_my_preferences(db, concert_id, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no preferences set for this concert")
    return result

@router.delete("/mine/{concert_id}")
async def delete_my_preferences(concert_id: int, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    result = clear_my_preferences(db, concert_id, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="You have no preferences set for this concert")
    return {"msg": "Preferences cleared successfully"}
