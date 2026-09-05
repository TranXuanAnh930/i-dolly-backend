import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.db.models.notification import Notification
from app.db.models.user import Users

# Fan-facing / self-scoped, same shape as lottery_entry_service: nothing here
# creates a notification — that's the future Celery/SendGrid task's job
# (docs/project_status.md §5) — this only covers a user reading their own.

def get_my_notifications(db: Session, current_user: Users, unread_only: bool = False):
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    result = query.order_by(Notification.created_at.desc()).all()
    if not result:
        return False
    return result

def mark_as_read(db: Session, notification_id: uuid.UUID, current_user: Users):
    notification = db.get(Notification, notification_id)
    if not notification:
        return "not_found"
    if notification.user_id != current_user.id:
        return "forbidden"
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return notification

def mark_all_as_read(db: Session, current_user: Users) -> int:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .update({"is_read": True, "read_at": datetime.now(timezone.utc)})
    )
    db.commit()
    return updated
