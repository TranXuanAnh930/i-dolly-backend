import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity import Users
from app.db.models.shared import Notification
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.shared import NotificationRead, NotificationUnreadCount
from app.services.shared.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])

# Meant to be polled every 15-30s by a client with no push/WebSocket layer
# (see docs/api-spec.md's Notifications section) — a tighter, count-only
# endpoint than /mine so a poller isn't paying for the full notification
# bodies on every tick. Budget sized well above any sane poll interval so a
# normal client never sees a 429; it's still capped, since an unbounded
# per-user endpoint is exactly what a runaway/misbehaving poller would hit.
@router.get("/unread-count", response_model=NotificationUnreadCount)
async def get_unread_count(current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(30, 60, user_key)), db: Session = Depends(get_db)) -> NotificationUnreadCount:
    return {"count": NotificationService.count_unread(db, current_user)}

@router.get("/mine", response_model=List[NotificationRead])
async def list_my_notifications(unread_only: bool = False, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(10, 60, user_key)), db: Session = Depends(get_db)) -> list[Notification]:
    result = NotificationService.get_my_notifications(db, current_user, unread_only)
    if not result:
        raise HTTPException(status_code=404, detail="You have no notifications")
    return result

@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(notification_id: uuid.UUID, current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(10, 60, user_key)), db: Session = Depends(get_db)) -> Notification:
    try:
        return NotificationService.mark_as_read(db, notification_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.post("/read-all", response_model=MessageResponse)
async def mark_all_notifications_read(current_user: Users = Depends(get_current_user), _: None = Depends(rate_limit(5, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    count = NotificationService.mark_all_as_read(db, current_user)
    return MessageResponse(msg=f"{count} notification(s) marked as read")
