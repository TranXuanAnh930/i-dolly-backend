import uuid
from unittest.mock import MagicMock

import pytest

from app.exception.common import ForbiddenError, NotFoundError

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# OTHER_ID for "a second, different row", MISSING_ID for "doesn't exist".
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def make_mock_user(id=DEFAULT_ID):
    user = MagicMock()
    user.id = id
    return user

def make_mock_notification(id=DEFAULT_ID, user_id=DEFAULT_ID, is_read=False):
    notification = MagicMock()
    notification.id = id
    notification.user_id = user_id
    notification.is_read = is_read
    return notification

# ───────────────────────────────────────────────────────────────
# Notification Service Tests
# ───────────────────────────────────────────────────────────────

class TestNotificationService:

    def test_create_notification_adds_but_does_not_commit(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()

        result = NotificationService.create_notification(db, DEFAULT_ID, "order_confirmation", order_id=DEFAULT_ID)

        db.add.assert_called_once()
        db.commit.assert_not_called()
        assert result.user_id == DEFAULT_ID
        assert result.type == "order_confirmation"
        assert result.order_id == DEFAULT_ID

    def test_count_unread(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        db.query().filter().count.return_value = 3

        result = NotificationService.count_unread(db, make_mock_user())
        assert result == 3

    def test_get_my_notifications_found(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        db.query().filter().order_by().all.return_value = [make_mock_notification()]

        result = NotificationService.get_my_notifications(db, make_mock_user())
        assert result is not None

    def test_get_my_notifications_empty(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        db.query().filter().order_by().all.return_value = []

        result = NotificationService.get_my_notifications(db, make_mock_user())
        assert result is None

    def test_get_my_notifications_unread_only_filters_twice(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        db.query().filter().filter().order_by().all.return_value = [make_mock_notification(is_read=False)]

        result = NotificationService.get_my_notifications(db, make_mock_user(), unread_only=True)
        assert result is not None

    def test_mark_as_read_not_found(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(NotFoundError):
            NotificationService.mark_as_read(db, MISSING_ID, make_mock_user())

    def test_mark_as_read_not_owner_forbidden(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        db.get.return_value = make_mock_notification(user_id=OTHER_ID)

        with pytest.raises(ForbiddenError):
            NotificationService.mark_as_read(db, DEFAULT_ID, make_mock_user(id=DEFAULT_ID))

    def test_mark_as_read_success(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        notification = make_mock_notification(user_id=DEFAULT_ID, is_read=False)
        db.get.return_value = notification

        result = NotificationService.mark_as_read(db, DEFAULT_ID, make_mock_user(id=DEFAULT_ID))

        assert result.is_read is True
        assert result.read_at is not None
        db.commit.assert_called_once()

    def test_mark_as_read_already_read_is_a_no_op(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        notification = make_mock_notification(user_id=DEFAULT_ID, is_read=True)
        db.get.return_value = notification

        result = NotificationService.mark_as_read(db, DEFAULT_ID, make_mock_user(id=DEFAULT_ID))

        assert result is notification
        db.commit.assert_not_called()

    def test_mark_all_as_read(self):
        from app.services.shared.notification_service import NotificationService

        db = MagicMock()
        db.query().filter().update.return_value = 5

        result = NotificationService.mark_all_as_read(db, make_mock_user())

        assert result == 5
        db.commit.assert_called_once()
