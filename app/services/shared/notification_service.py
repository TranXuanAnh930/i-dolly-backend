import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.identity import Users
from app.db.models.shared import Notification
from app.exception.common import ForbiddenError, NotFoundError
from app.schema.shared import NotificationType


class NotificationService:

    # Fan-facing / self-scoped, same shape as lottery_entry_service, PLUS the
    # producer side (create_notification/count_unread) that every purchase/
    # lottery/auth flow now calls into.

    @staticmethod
    def create_notification(db: Session, user_id: uuid.UUID, notification_type: NotificationType, **entity_ids: uuid.UUID | None) -> Notification:
        """Adds (does not commit) one notification row. Called from inside an
        existing service transaction (order_service.checkout,
        ticket_service.checkout_ticket, lottery_draw_service.draw_lottery,
        user_service.verify_rtoken) so the notification and the business event
        it describes land in the same commit — no separate round trip, and no
        orphaned notification if the caller's transaction rolls back.
        `entity_ids` is whichever one of order_id/ticket_id/lottery_entry_id/
        concert_id matches `notification_type` (database-design.md §3.19) —
        the caller decides which, this just forwards it onto the model."""
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
    def get_my_notifications(db: Session, current_user: Users, unread_only: bool = False) -> list[Notification] | None:
        query = db.query(Notification).filter(Notification.user_id == current_user.id)
        if unread_only:
            query = query.filter(Notification.is_read == False)
        result = query.order_by(Notification.created_at.desc()).all()
        if not result:
            return None
        return result

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
