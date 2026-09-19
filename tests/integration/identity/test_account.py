import uuid

import pytest
from fastapi.testclient import TestClient

from app.utils.jwt_manager import create_email_verification_token
from main import app

client = TestClient(app)

# ───────────────────────────────────────────────────────────────
# Fixtures — reset_rate_limits is shared, autouse, in
# tests/integration/conftest.py; every test module under this directory
# gets it automatically, no per-file import needed. ensure_user_exists is
# file-local: register_user is idempotent (a duplicate returns 400, never
# checked here), and every test in every integration module needs the same
# demo fan account to exist.
# ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def ensure_user_exists():
    register_user()
    yield

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def register_user(email="demo@example.com", password="demo123", name="demo"):
    return client.post("/account/register", json={
        "name": name, "email": email, "password": password
    })

def login_user(email="demo@example.com", password="demo123"):
    return client.post("/account/login", data={
        "username": email, "password": password
    })

def auth_headers(email="demo@example.com", password="demo123"):
    res = login_user(email, password)
    token = res.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}

# ───────────────────────────────────────────────────────────────
# POST /account/refresh
# ───────────────────────────────────────────────────────────────

def test_refresh_missing_cookie():
    response = client.post("/account/refresh")
    assert response.status_code == 401

def test_refresh_invalid_token():
    response = client.post("/account/refresh", cookies={"refresh_token": "not-a-real-token"})
    assert response.status_code == 401

def test_refresh_success_issues_new_access_token():
    email, password = f"refresh-{uuid.uuid4()}@example.com", "pass123"
    register_user(email=email, password=password)
    login_response = login_user(email, password)
    # secure=True on the cookie — TestClient's jar won't replay it over the
    # plain-http base_url automatically, so it's passed explicitly, same
    # workaround as test_profile.py's logout tests.
    refresh_token = login_response.cookies.get("refresh_token")
    assert refresh_token

    response = client.post("/account/refresh", cookies={"refresh_token": refresh_token})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    # The new access token actually works.
    me_response = client.get("/profile/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email

def test_refresh_after_logout_rejected():
    email, password = f"refreshlogout-{uuid.uuid4()}@example.com", "pass123"
    register_user(email=email, password=password)
    refresh_token = login_user(email, password).cookies.get("refresh_token")

    logout_response = client.post("/profile/logout", cookies={"refresh_token": refresh_token})
    assert logout_response.status_code == 200

    response = client.post("/account/refresh", cookies={"refresh_token": refresh_token})
    assert response.status_code == 401

# ───────────────────────────────────────────────────────────────
# POST /account/verify-request / GET /account/verify
# ───────────────────────────────────────────────────────────────

def test_verify_request_unauthenticated():
    response = client.post("/account/verify-request")
    assert response.status_code == 401

def test_verify_request_success():
    response = client.post("/account/verify-request", headers=auth_headers())
    assert response.status_code == 200

def test_verify_email_invalid_token():
    response = client.get("/account/verify", params={"token": "garbage-token"})
    assert response.status_code == 400

def test_verify_email_success_then_marks_user_verified():
    email, password = f"verify-{uuid.uuid4()}@example.com", "pass123"
    register_response = register_user(email=email, password=password)
    user_id = register_response.json()["id"]
    # Minted directly the same way AuthService.email_verification_process
    # does — the real token is only ever emailed (send_email just prints in
    # DEBUG mode, nothing an HTTP-only test can capture), so this mirrors
    # test_profile.py's set-password tests' same out-of-band minting.
    token = create_email_verification_token(uuid.UUID(user_id))

    response = client.get("/account/verify", params={"token": token})
    assert response.status_code == 200

    me_response = client.get("/profile/me", headers=auth_headers(email, password))
    assert me_response.json()["is_verified"] is True

def test_verify_email_already_verified_rejected():
    email, password = f"verifytwice-{uuid.uuid4()}@example.com", "pass123"
    register_response = register_user(email=email, password=password)
    user_id = register_response.json()["id"]

    token = create_email_verification_token(uuid.UUID(user_id))
    assert client.get("/account/verify", params={"token": token}).status_code == 200

    token_again = create_email_verification_token(uuid.UUID(user_id))
    response = client.get("/account/verify", params={"token": token_again})
    assert response.status_code == 401
