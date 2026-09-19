import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# Ids are UUIDs now, not autoincrementing ints. None of these tests depend on
# a real row existing at this id — every one asserts 401/403 (auth/authz
# short-circuits before an id lookup happens) or 404 via this intentionally
# nonexistent sentinel. A plain int literal here would now fail path/body
# validation with 422 before ever reaching the logic these tests target.
FAKE_ID = "11111111-1111-1111-1111-111111111111"

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
# Auth Tests
# ───────────────────────────────────────────────────────────────

def test_register_fresh():
    response = register_user(email="fresh@example.com", password="fresh123", name="fresh")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "fresh@example.com"
    assert "id" in data
    assert "password" not in data

    headers = auth_headers(email="fresh@example.com", password="fresh123")
    response = client.delete("/profile/delete", headers=headers)
    assert response.status_code == 200
    assert "msg"  in response.json() 
       
def test_register_duplicate():
    response = register_user()
    assert response.status_code == 400

def test_login():
    response = login_user()
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data

def test_login_wrong_password():
    response = login_user(password="wrongpassword")
    assert response.status_code in (400, 401)

def test_protected_route_without_token():
    response = client.get("/cart/see_cart")
    assert response.status_code == 401
