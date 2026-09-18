import threading

import pytest
from fastapi import HTTPException

from app.cache.rate_limit import ip_key, rate_limit
from tests.conftest import fake_redis

# ─────────────────────────────────────────────────────────────
# Fake Request — rate_limit()'s closure only ever touches
# request.scope["route"].path and request.client.host (via ip_key),
# so a real Starlette Request isn't needed, just these two attributes.
# ─────────────────────────────────────────────────────────────


class _FakeRoute:
    def __init__(self, path):
        self.path = path


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, path="/test-route", ip="1.2.3.4"):
        self.scope = {"route": _FakeRoute(path)}
        self.client = _FakeClient(ip)


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
