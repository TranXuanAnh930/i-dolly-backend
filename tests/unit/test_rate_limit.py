import logging
import threading
from unittest.mock import patch

import pytest
import redis
from fastapi import HTTPException
from starlette.datastructures import Headers

from app.cache.rate_limit import (
    FORGOT_PASSWORD_LIMIT,
    LOGIN_FAIL_LIMIT,
    LOGIN_FAIL_WINDOW,
    clear_login_failures,
    client_ip,
    forgot_password_limit_exceeded,
    ip_key,
    login_attempts_exceeded,
    rate_limit,
    record_login_failure,
)
from app.config.settings import settings
from tests.conftest import fake_redis

# ─────────────────────────────────────────────────────────────
# Fake Request — rate_limit()'s closure only ever touches
# request.scope["route"].path, request.client.host and (when proxies are
# trusted) request.headers, via ip_key, so a real Starlette Request isn't
# needed, just these attributes.
# ─────────────────────────────────────────────────────────────


class _FakeRoute:
    def __init__(self, path):
        self.path = path


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, path="/test-route", ip="1.2.3.4", forwarded_for=()):
        self.scope = {"route": _FakeRoute(path)}
        self.client = _FakeClient(ip)
        # One X-Forwarded-For header line per item.
        self.headers = Headers(raw=[(b"x-forwarded-for", value.encode()) for value in forwarded_for])


@pytest.fixture(autouse=True)
def _clear_rate_limit_keys():
    # rate_limit() keys the counter on route + identity (app/cache/rate_limit.py's
    # _route_key), so leftover keys from one test could bleed into the next test's
    # count if they happen to reuse a path/ip — same reasoning as
    # tests/integration/conftest.py's reset_rate_limits fixture, just scoped here
    # instead of shared, since these are the only unit tests touching rate_limit.
    for key in fake_redis.scan_iter("rate:*"):
        fake_redis.delete(key)
    yield


class TestRateLimit:
    def test_allows_exactly_limit_requests_then_blocks(self):
        limiter = rate_limit(limit=5, window=60, key_func=ip_key)
        request = _FakeRequest()

        for _ in range(5):
            limiter(request)  # must not raise

        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        assert exc_info.value.status_code == 429

    def test_counter_always_has_a_ttl(self):
        limiter = rate_limit(limit=5, window=60, key_func=ip_key)
        request = _FakeRequest(path="/ttl-route")

        limiter(request)
        key = ip_key(request)
        assert int(fake_redis.get(key)) == 1
        assert 0 < fake_redis.ttl(key) <= 60

        limiter(request)
        assert int(fake_redis.get(key)) == 2
        assert 0 < fake_redis.ttl(key) <= 60

    def test_concurrent_requests_never_exceed_the_limit(self):
        # Proves the fix for the non-atomic get-then-setex/incr race: fire more
        # concurrent requests than the limit allows, on one shared key, and
        # confirm the counter still caps at exactly `limit` — not more (the
        # race would let concurrent requests all read a stale count and each
        # "pass", overshooting the limit) and not fewer (a bug that double-counts
        # would trip the limit early, rejecting requests that should be allowed).
        limit = 10
        request_count = 50
        limiter = rate_limit(limit=limit, window=60, key_func=ip_key)
        request = _FakeRequest(path="/concurrent-route")

        allowed = 0
        blocked = 0
        lock = threading.Lock()

        def fire():
            nonlocal allowed, blocked
            try:
                limiter(request)
            except HTTPException:
                with lock:
                    blocked += 1
            else:
                with lock:
                    allowed += 1

        threads = [threading.Thread(target=fire) for _ in range(request_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert allowed == limit
        assert blocked == request_count - limit


PEER = "10.0.0.1"  # the proxy's address, as the app sees the connection


class TestClientIp:
    def test_no_trusted_proxy_ignores_the_header(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0)
        request = _FakeRequest(ip=PEER, forwarded_for=["6.6.6.6"])
        assert client_ip(request) == PEER

    def test_one_hop_takes_the_rightmost_entry(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        request = _FakeRequest(ip=PEER, forwarded_for=["6.6.6.6, 203.0.113.7"])
        assert client_ip(request) == "203.0.113.7"

    def test_two_hops_skip_the_inner_proxy(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)
        request = _FakeRequest(ip=PEER, forwarded_for=["6.6.6.6, 203.0.113.7, 172.16.0.9"])
        assert client_ip(request) == "203.0.113.7"

    def test_several_header_lines_are_combined(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)
        request = _FakeRequest(ip=PEER, forwarded_for=["6.6.6.6, 203.0.113.7", "172.16.0.9"])
        assert client_ip(request) == "203.0.113.7"

    def test_header_shorter_than_hops_falls_back_to_the_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)
        request = _FakeRequest(ip=PEER, forwarded_for=["203.0.113.7"])
        assert client_ip(request) == PEER

    def test_missing_header_falls_back_to_the_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        assert client_ip(_FakeRequest(ip=PEER)) == PEER

    def test_invalid_entry_falls_back_to_the_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        request = _FakeRequest(ip=PEER, forwarded_for=["6.6.6.6, not-an-ip"])
        assert client_ip(request) == PEER

    def test_rotating_the_spoofed_entry_does_not_change_the_bucket(self, monkeypatch):
        # bugs.md #7: a different fake leftmost entry per request must not mint a new bucket.
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        limiter = rate_limit(limit=3, window=60, key_func=ip_key)
        for i in range(3):
            limiter(_FakeRequest(path="/spoof-route", ip=PEER, forwarded_for=[f"6.6.6.{i}, 203.0.113.7"]))
        with pytest.raises(HTTPException) as exc_info:
            limiter(_FakeRequest(path="/spoof-route", ip=PEER, forwarded_for=["6.6.6.99, 203.0.113.7"]))
        assert exc_info.value.status_code == 429


class TestLoginFailureLimit:
    def test_exceeded_after_limit_failures(self):
        for _ in range(LOGIN_FAIL_LIMIT - 1):
            record_login_failure("fan@example.com")
        assert not login_attempts_exceeded("fan@example.com")
        record_login_failure("fan@example.com")
        assert login_attempts_exceeded("fan@example.com")

    def test_other_emails_are_unaffected(self):
        for _ in range(LOGIN_FAIL_LIMIT):
            record_login_failure("fan@example.com")
        assert not login_attempts_exceeded("other@example.com")

    def test_email_is_matched_case_insensitively(self):
        for _ in range(LOGIN_FAIL_LIMIT):
            record_login_failure("Fan@Example.com")
        assert login_attempts_exceeded(" fan@example.com ")

    def test_clear_resets_the_count(self):
        for _ in range(LOGIN_FAIL_LIMIT):
            record_login_failure("fan@example.com")
        clear_login_failures("fan@example.com")
        assert not login_attempts_exceeded("fan@example.com")

    def test_counter_has_a_ttl_and_no_email_in_the_key(self):
        record_login_failure("fan@example.com")
        keys = list(fake_redis.scan_iter("rate:login_fail:*"))
        assert len(keys) == 1
        assert b"fan@example.com" not in keys[0]
        assert 0 < fake_redis.ttl(keys[0]) <= LOGIN_FAIL_WINDOW


class TestForgotPasswordLimit:
    def test_allows_limit_requests_then_reports_exceeded(self):
        for _ in range(FORGOT_PASSWORD_LIMIT):
            assert not forgot_password_limit_exceeded("fan@example.com")
        assert forgot_password_limit_exceeded("fan@example.com")
        assert not forgot_password_limit_exceeded("other@example.com")


class TestRedisErrorsAreLogged:
    def test_limiter_fails_open_and_logs_a_warning(self, caplog):
        limiter = rate_limit(limit=1, window=60, key_func=ip_key)
        with caplog.at_level(logging.WARNING, logger="app.cache.rate_limit"), \
             patch("app.cache.rate_limit.redis_client.pipeline", side_effect=redis.ConnectionError("refused")):
            limiter(_FakeRequest(path="/redis-down"))  # must not raise
            limiter(_FakeRequest(path="/redis-down"))  # over the limit, but Redis is down: allowed

        assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.WARNING]
        assert "refused" in caplog.records[0].getMessage()
        # One line per request, not a stack trace each.
        assert caplog.records[0].exc_info is None

    def test_per_email_limits_fail_open_and_log(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.cache.rate_limit"), \
             patch("app.cache.rate_limit.redis_client.get", side_effect=redis.ConnectionError("refused")):
            assert login_attempts_exceeded("fan@example.com") is False
        assert len(caplog.records) == 1
