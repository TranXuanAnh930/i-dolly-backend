import uuid
from unittest.mock import MagicMock, patch

import pytest

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# MISSING_ID for "doesn't exist".
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def make_mock_user(id=DEFAULT_ID, name="Test", email="test@example.com", is_admin=False, is_verified=True, role="fan"):
    user = MagicMock()
    user.id = id
    user.name = name
    user.email = email
    user.is_admin = is_admin
    user.is_verified = is_verified
    user.hashed_password = "$2b$12$hashedpassword"
    user.role = role  # matches Users.role's real DB default (database-design.md §3.1)
    return user


# ───────────────────────────────────────────────────────────────
# User Service Tests
# ───────────────────────────────────────────────────────────────

class TestUserService:

    def test_change_password_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user()

        with patch("app.services.identity.user_service.verify_password", return_value=True), \
             patch("app.services.identity.user_service.hash_password", return_value="new_hashed"):
            result = UserService.change_password_process(db, mock_user, "oldpass", "newpass")

        assert result is True
        db.commit.assert_called_once()

    def test_change_password_wrong_old(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user()

        with patch("app.services.identity.user_service.verify_password", return_value=False):
            result = UserService.change_password_process(db, mock_user, "wrong", "newpass")

        assert result is None

    def test_promote_admin_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user(role="fan")
        db.get.return_value = mock_user

        result = UserService.promote_admin(db, DEFAULT_ID)
        assert result is True
        # role is the actual source of truth for require_admin — is_admin is still
        # set too, since it isn't dropped yet, but role is what grants access.
        assert mock_user.role == "admin"
        assert mock_user.is_admin is True

    def test_promote_admin_already_admin(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user(role="admin")
        db.get.return_value = mock_user

        result = UserService.promote_admin(db, DEFAULT_ID)
        assert result is False

    def test_promote_admin_user_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.get.return_value = None

        result = UserService.promote_admin(db, MISSING_ID)
        assert result is None

    def test_create_manager_success(self):
        from app.schema.identity import ManagerCreate
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None  # no existing user with this email
        db.get.return_value = MagicMock()  # company exists
        data = ManagerCreate(name="Manager", email="manager@example.com", password="pass123", company_id=DEFAULT_ID)

        result = UserService.create_manager_user(db, data)
        assert result.role == "manager"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_create_manager_email_taken(self):
        from app.exception.common import BadRequestError
        from app.schema.identity import ManagerCreate
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = make_mock_user()
        data = ManagerCreate(name="Manager", email="manager@example.com", password="pass123", company_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            UserService.create_manager_user(db, data)

    def test_create_manager_company_not_found(self):
        from app.exception.common import NotFoundError
        from app.schema.identity import ManagerCreate
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None
        db.get.return_value = None
        data = ManagerCreate(name="Manager", email="manager@example.com", password="pass123", company_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            UserService.create_manager_user(db, data)

    def test_revoke_token_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_token = MagicMock()
        mock_token.revoked = False
        db.query().filter().first.return_value = mock_token

        result = UserService.revoke_token(db, "token123")
        assert result is True
        assert mock_token.revoked is True

    def test_revoke_token_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = UserService.revoke_token(db, "nonexistent")
        assert result is False

    def test_delete_user_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user()
        db.get.return_value = mock_user

        result = UserService.delete_user(db, DEFAULT_ID)
        assert result is True
        db.delete.assert_called_once_with(mock_user)

    def test_delete_user_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.get.return_value = None

        result = UserService.delete_user(db, MISSING_ID)
        assert result is None

    def test_reset_password_process_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user()
        db.query().filter().first.return_value = mock_user

        with patch("app.services.identity.user_service.create_password_reset_token", return_value="reset_tok"), \
             patch("app.services.identity.user_service.settings") as mock_settings, \
             patch("app.services.identity.user_service.celery_app.send_task") as mock_send_task:
            mock_settings.FRONTEND_BASE_URL = "http://localhost:8080"
            result = UserService.reset_password_process(db, "test@example.com")

        assert result is True
        mock_send_task.assert_called_once()
        assert mock_send_task.call_args[0][0] == "app.tasks.email.send_email"
        # The email carries a clickable reset link (frontend's own
        # /reset-password page, token in the query string) rather than a
        # bare token the fan has to copy-paste in themselves.
        email_body = mock_send_task.call_args.kwargs["args"][2]
        assert "http://localhost:8080/reset-password?token=reset_tok" in email_body

    def test_reset_password_process_email_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None

        # Always returns True, matched user or not — the router gives the
        # same generic response either way so this can't be used to
        # enumerate registered emails (user_service.py's own comment).
        with patch("app.services.identity.user_service.celery_app.send_task") as mock_send_task:
            result = UserService.reset_password_process(db, "nope@example.com")

        assert result is True
        mock_send_task.assert_not_called()

    def test_verify_rtoken_invalid_token(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()

        with patch("app.services.identity.user_service.verify_rtoken_and_get_user_id", return_value=None):
            result = UserService.verify_rtoken(db, "bad-token", "newpass")

        assert result is False
        db.commit.assert_not_called()

    def test_verify_rtoken_user_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None

        with patch("app.services.identity.user_service.verify_rtoken_and_get_user_id", return_value=DEFAULT_ID):
            result = UserService.verify_rtoken(db, "good-token", "newpass")

        assert result is None
        db.commit.assert_not_called()

    def test_verify_rtoken_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user(id=DEFAULT_ID)
        db.query().filter().first.return_value = mock_user

        with patch("app.services.identity.user_service.verify_rtoken_and_get_user_id", return_value=DEFAULT_ID), \
             patch("app.services.identity.user_service.hash_password", return_value="new_hashed"), \
             patch("app.services.identity.user_service.NotificationService.create_notification") as mock_notify:
            result = UserService.verify_rtoken(db, "good-token", "newpass")

        assert result is True
        assert mock_user.hashed_password == "new_hashed"
        # Revokes every existing refresh token, same as a fresh login — an
        # attacker's already-held session shouldn't survive the reset meant
        # to lock them out.
        db.query().filter().update.assert_called_once_with({"revoked": True})
        mock_notify.assert_called_once_with(db, DEFAULT_ID, "password_reset")
        db.commit.assert_called_once()
