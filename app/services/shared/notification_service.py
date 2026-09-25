import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.identity import Users
from app.db.models.shared import Notification
from app.exception.common import ForbiddenError, NotFoundError
from app.schema.shared import NotificationType


class NotificationService:

    # Fans read and manage their own notifications; other services create them.

    @staticmethod
    def create_notification(db: Session, user_id: uuid.UUID, notification_type: NotificationType, **entity_ids: uuid.UUID | None) -> Notification:
        """Add (without committing) a notification, so it commits or rolls back with the caller's
        transaction. Pass the entity id matching the type: order_id, ticket_id, lottery_entry_id
        or concert_id."""
        notification = Notification(user_id=user_id, type=notification_type, **entity_ids)
        db.add(notification)
        return notification

    @staticmethod
    def count_unread(db: Session, current_user: Users) -> int:
        return (
            db.query(Notification)
            .filter(Notification.user_id == current_user.id, Notification.is_read == False)
            .count()
        )

    @staticmethod
    def get_my_notifications(db: Session, current_user: Users, unread_only: bool = False) -> list[Notification]:
        query = db.query(Notification).filter(Notification.user_id == current_user.id)
        if unread_only:
            query = query.filter(Notification.is_read == False)
        return query.order_by(Notification.created_at.desc()).all()

    @staticmethod
    def mark_as_read(db: Session, notification_id: uuid.UUID, current_user: Users) -> Notification:
        notification = db.get(Notification, notification_id)
        if not notification:
            raise NotFoundError("Notification not found")
        if notification.user_id != current_user.id:
            raise ForbiddenError("This notification doesn't belong to you")
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(notification)
        return notification

    @staticmethod
    def mark_all_as_read(db: Session, current_user: Users) -> int:
        updated = (
            db.query(Notification)
            .filter(Notification.user_id == current_user.id, Notification.is_read == False)
            .update({"is_read": True, "read_at": datetime.now(timezone.utc)})
        )
        db.commit()
        return updated
