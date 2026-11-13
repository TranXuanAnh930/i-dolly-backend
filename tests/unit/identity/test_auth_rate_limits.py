from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cache.rate_limit import FORGOT_PASSWORD_LIMIT, LOGIN_FAIL_LIMIT
from app.config.settings import settings
from app.deps.db import get_db
from app.exception.handlers import register_exception_handlers
from app.router.identity.auth import router as auth_router
from app.router.identity.user import router as user_router
from tests.conftest import fake_redis

# The login and forgot-password routes over HTTP, with the database mocked out: the real routers,
# rate-limit dependencies and Redis commands (fakeredis), but no Postgres.

app = FastAPI()
register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(user_router)
app.dependency_overrides[get_db] = lambda: MagicMock()
client = TestClient(app)

REAL_IP = "203.0.113.7"


@pytest.fixture(autouse=True)
def _clear_rate_limit_keys():
    for key in fake_redis.scan_iter("rate:*"):
        fake_redis.delete(key)
    yield


def _login(email, forwarded_for=None):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    return client.post("/account/login", data={"username": email, "password": "wrong"}, headers=headers)


@patch("app.router.identity.auth.AuthService.authenticate_user", return_value=None)
class TestLoginLimits:
    def test_spoofed_forwarded_for_does_not_bypass_the_ip_limit(self, _auth, monkeypatch):
        # bugs.md #7. The proxy appends the real IP on the right; the client rotates the left entry.
        # A different email each time keeps the per-account limit out of the way.
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        statuses = [_login(f"user{i}@example.com", f"6.6.6.{i}, {REAL_IP}").status_code for i in range(11)]
        assert statuses[:10] == [401] * 10
        assert statuses[10] == 429

    def test_different_real_ips_get_separate_buckets(self, _auth, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        statuses = [_login(f"user{i}@example.com", f"6.6.6.6, 198.51.100.{i}").status_code for i in range(11)]
        assert statuses == [401] * 11

    def test_failed_logins_for_one_email_are_limited_across_ips(self, _auth, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        responses = [_login("fan@example.com", f"198.51.100.{i}") for i in range(LOGIN_FAIL_LIMIT + 1)]
        assert [r.status_code for r in responses[:-1]] == [401] * LOGIN_FAIL_LIMIT
        assert responses[-1].status_code == 429
        assert responses[-1].json()["code"] == "too_many_login_attempts"
        # Another account is unaffected.
        assert _login("other@example.com", "198.51.100.200").status_code == 401

    def test_locked_account_is_not_checked_against_the_password(self, auth, monkeypatch):
        for _ in range(LOGIN_FAIL_LIMIT):
            _login("fan@example.com")
        auth.reset_mock()
        assert _login("fan@example.com").status_code == 429
        auth.assert_not_called()


def test_successful_login_clears_the_failure_count():
    with patch("app.router.identity.auth.AuthService.authenticate_user", return_value=None):
        for _ in range(LOGIN_FAIL_LIMIT - 1):
            _login("fan@example.com")
    tokens = {"access_token": "a", "refresh_token": "r"}
    with patch("app.router.identity.auth.AuthService.authenticate_user", return_value=MagicMock()), \
         patch("app.router.identity.auth.AuthService.create_tokens", return_value=tokens):
        assert _login("fan@example.com").status_code == 200
    assert not list(fake_redis.scan_iter("rate:login_fail:*"))


@patch("app.router.identity.user.UserService.reset_password_process", return_value=True)
def test_forgot_password_is_limited_per_email_across_ips(reset, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)

    def forgot(email, ip):
        return client.post("/profile/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})

    statuses = [forgot("fan@example.com", f"198.51.100.{i}").status_code for i in range(FORGOT_PASSWORD_LIMIT + 1)]
    assert statuses == [200] * FORGOT_PASSWORD_LIMIT + [429]
    assert reset.call_count == FORGOT_PASSWORD_LIMIT
    assert forgot("other@example.com", "198.51.100.200").status_code == 200
