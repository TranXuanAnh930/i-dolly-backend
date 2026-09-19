import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()

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
# Auth Service Tests
# ───────────────────────────────────────────────────────────────

class TestAuthService:

    def test_create_user_success(self):
        from app.schema.identity import UserCreate
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().first.return_value = None
        mock_user = MagicMock()
        mock_user.id = DEFAULT_ID
        db.add.return_value = None
        db.refresh.side_effect = lambda x: setattr(x, 'id', DEFAULT_ID)
        user_data = UserCreate(name="John", email="john@example.com", password="pass123")

        with patch("app.services.identity.auth_service.hash_password", return_value="hashed"):
            result = AuthService.create_user(db, user_data)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not False

    def test_create_user_duplicate_email(self):
        from app.schema.identity import UserCreate
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().first.return_value = make_mock_user()
        user_data = UserCreate(name="John", email="test@example.com", password="pass123")

        result = AuthService.create_user(db, user_data)
        assert result is False

    def test_authenticate_user_success(self):
        from app.services.identity.auth_service import AuthService

        mock_user = make_mock_user()
        db = MagicMock()
        db.query().filter().first.return_value = mock_user

        with patch("app.services.identity.auth_service.verify_password", return_value=True):
            result = AuthService.authenticate_user(db, "test@example.com", "password")

        assert result == mock_user

    def test_authenticate_user_wrong_password(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().first.return_value = make_mock_user()

        with patch("app.services.identity.auth_service.verify_password", return_value=False):
            result = AuthService.authenticate_user(db, "test@example.com", "wrong")

        assert result is None

    def test_authenticate_user_not_found(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = AuthService.authenticate_user(db, "nope@example.com", "password")
        assert result is None

    def test_create_tokens(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().update.return_value = 0
        mock_user = make_mock_user()

        with patch("app.services.identity.auth_service.create_access_token", return_value="access_tok"):
            result = AuthService.create_tokens(db, mock_user)

        assert "access_token" in result
        assert "refresh_token" in result
        assert result["access_token"] == "access_tok"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_verify_refresh_token_valid(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        mock_token = MagicMock()
        mock_token.revoked = False
        mock_token.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        mock_token.user_id = DEFAULT_ID
        db.query().filter().first.return_value = mock_token

        mock_user = make_mock_user()
        db.query().filter().first.side_effect = [mock_token, mock_user]

        result = AuthService.verify_refresh_token(db, "valid-token")
        # Result should be the user (from second query)
        assert result is not None

    def test_verify_refresh_token_expired(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        mock_token = MagicMock()
        mock_token.revoked = False
        mock_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.query().filter().first.return_value = mock_token

        result = AuthService.verify_refresh_token(db, "expired-token")
        assert result is None

    def test_verify_email_token_success(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        mock_user = make_mock_user()
        mock_user.is_verified = False
        db.query().filter().first.return_value = mock_user

        with patch("app.services.identity.auth_service.verify_token_and_get_user_id", return_value=DEFAULT_ID):
            result = AuthService.verify_email_token(db, "valid-email-token")

        assert result is True
        assert mock_user.is_verified is True
        db.commit.assert_called_once()

    def test_verify_email_token_invalid(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        with patch("app.services.identity.auth_service.verify_token_and_get_user_id", return_value=None):
            result = AuthService.verify_email_token(db, "invalid-token")
        assert result is None

    def test_email_verification_process(self):
        from app.services.identity.auth_service import AuthService

        mock_user = make_mock_user()

        with patch("app.services.identity.auth_service.create_email_verification_token", return_value="tok123"), \
             patch("app.services.identity.auth_service.celery_app.send_task") as mock_send_task:
            result = AuthService.email_verification_process(mock_user)

        mock_send_task.assert_called_once()
        assert mock_send_task.call_args[0][0] == "app.tasks.email.send_email"
        assert result is None

    def test_cleanup_expired_tokens(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().delete.return_value = 5

        result = AuthService.cleanup_expired_tokens(db)
        assert result == 5
        db.commit.assert_called_once()
