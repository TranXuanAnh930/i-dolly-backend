import uuid
from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.notification import NotificationRead
from app.services.notification_service import get_my_notifications, mark_as_read, mark_all_as_read

router = APIRouter(prefix="/notifications", tags=["Notifications"])

def _raise_for(result):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="This notification doesn't belong to you")
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Notification not found")

@router.get("/mine", response_model=List[NotificationRead])
async def list_my_notifications(unread_only: bool = False, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    result = get_my_notifications(db, current_user, unread_only)
    if not result:
        raise HTTPException(status_code=404, detail="You have no notifications")
    return result

@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(notification_id: uuid.UUID, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    result = mark_as_read(db, notification_id, current_user)
    if isinstance(result, str):
        _raise_for(result)
    return result

@router.post("/read-all")
async def mark_all_notifications_read(current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    count = mark_all_as_read(db, current_user)
    return {"msg": f"{count} notification(s) marked as read"}
