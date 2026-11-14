import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.cache.rate_limit import rate_limit, user_key, user_or_ip_key
from app.deps.auth import get_current_user, get_current_user_optional
from app.deps.db import get_db
from tests.conftest import fake_redis

# bugs.md #22: user_key / user_or_ip_key read request.state.user, which only exists once the auth
# dependency has run. The limiter now depends on that auth dependency itself, so the order a route
# lists its dependencies in no longer matters. Auth is real (get_current_user and friends) with the
# token lookup patched: a token "user-<n>" is user n, anything else is invalid.

USERS = {f"user-{n}": SimpleNamespace(id=uuid.uuid4()) for n in range(2)}

app = FastAPI()
app.dependency_overrides[get_db] = lambda: MagicMock()


@app.get("/limiter-first")
def limiter_first(_: None = Depends(rate_limit(2, 60, user_key)), user=Depends(get_current_user)) -> dict:
    return {"user": str(user.id)}


@app.get("/no-auth-dependency")
def no_auth_dependency(_: None = Depends(rate_limit(2, 60, user_key))) -> dict:
    return {"ok": True}


@app.get("/optional-limiter-first")
def optional_limiter_first(_: None = Depends(rate_limit(2, 60, user_or_ip_key)), user=Depends(get_current_user_optional)) -> dict:
    return {"user": str(user.id) if user else None}


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _auth_and_clean_redis():
    for key in fake_redis.scan_iter("rate:*"):
        fake_redis.delete(key)
    with patch("app.deps.auth._user_from_token", side_effect=lambda token, db: USERS.get(token)) as lookup:
        yield lookup


def get(path, token=None):
    return client.get(path, headers={"Authorization": f"Bearer {token}"} if token else {})


def test_limiter_listed_before_auth_answers_401_without_a_token():
    # Before the fix this was a 500: user_key ran first and request.state.user didn't exist.
    assert get("/limiter-first").status_code == 401
    assert get("/limiter-first", "bad-token").status_code == 401


def test_limiter_listed_before_auth_counts_per_user():
    assert [get("/limiter-first", "user-0").status_code for _ in range(3)] == [200, 200, 429]
    # Another user has their own budget.
    assert get("/limiter-first", "user-1").status_code == 200


def test_auth_runs_once_per_request(_auth_and_clean_redis):
    # The route and the limiter both depend on get_current_user; FastAPI resolves it once.
    assert get("/limiter-first", "user-0").status_code == 200
    assert _auth_and_clean_redis.call_count == 1


def test_user_limiter_on_a_route_without_auth_requires_login():
    assert get("/no-auth-dependency").status_code == 401
    assert get("/no-auth-dependency", "user-0").status_code == 200


def test_optional_limiter_listed_first_keys_signed_in_users_by_user():
    # Before the fix a signed-in user fell into the IP bucket, shared with every guest behind
    # the same address.
    assert [get("/optional-limiter-first", "user-0").status_code for _ in range(3)] == [200, 200, 429]
    assert get("/optional-limiter-first", "user-1").status_code == 200
    assert get("/optional-limiter-first").status_code == 200


def test_optional_limiter_keys_guests_by_ip():
    assert [get("/optional-limiter-first").status_code for _ in range(3)] == [200, 200, 429]
    # Signed-in users aren't in the guests' bucket.
    assert get("/optional-limiter-first", "user-0").status_code == 200
