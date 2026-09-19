import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.identity import Users
from app.db.session import session as db_session
from app.utils.hashing import hash_password
from app.utils.jwt_manager import create_access_token
from main import app

client = TestClient(app)

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

# Venues are admin-only (venue.py's own comment: shared, platform-level
# data, not owned by one company) — a fresh test DB has no admin reachable
# through the public API, so the first one is minted directly via a real DB
# row, same as test_profile.py's admin_headers.
@pytest.fixture
def admin_headers():
    db = db_session()
    admin = Users(
        name="Admin", email=f"admin-{uuid.uuid4()}@example.com",
        hashed_password=hash_password("adminpass123"), role="admin", is_verified=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    token = create_access_token({"sub": str(admin.id)})
    yield {"Authorization": f"Bearer {token}"}
    db.delete(admin)
    db.commit()
    db.close()

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

def venue_payload(**overrides):
    payload = {
        "name": f"Arena {uuid.uuid4()}", "address": "1 Main St", "city": "Tokyo",
        "country": "Japan", "total_capacity": 5000, "contact_info": None,
    }
    payload.update(overrides)
    return payload

# ───────────────────────────────────────────────────────────────
# POST /venues/add
# ───────────────────────────────────────────────────────────────

def test_add_venue_unauthenticated():
    response = client.post("/venues/add", json=venue_payload())
    assert response.status_code == 401

def test_add_venue_requires_admin():
    response = client.post("/venues/add", json=venue_payload(), headers=auth_headers())
    assert response.status_code == 403

def test_add_venue_success(admin_headers):
    response = client.post("/venues/add", json=venue_payload(name="New Arena"), headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Arena"
    assert "id" in data
    # Derived by Postgres (GENERATED ALWAYS) from total_capacity, never client-settable.
    assert data["size"] in ("small", "medium", "large", "stadium")

# ───────────────────────────────────────────────────────────────
# GET /venues/all, GET /venues/{id}
# ───────────────────────────────────────────────────────────────

def test_list_venues_includes_added_venue(admin_headers):
    add_response = client.post("/venues/add", json=venue_payload(name="Listed Arena"), headers=admin_headers)
    venue_id = add_response.json()["id"]

    response = client.get("/venues/all")
    assert response.status_code == 200
    assert any(v["id"] == venue_id for v in response.json())

def test_get_venue_by_id_found(admin_headers):
    add_response = client.post("/venues/add", json=venue_payload(name="Findable Arena"), headers=admin_headers)
    venue_id = add_response.json()["id"]

    response = client.get(f"/venues/{venue_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Findable Arena"

def test_get_venue_by_id_not_found():
    response = client.get(f"/venues/{FAKE_ID}")
    assert response.status_code == 404

# ───────────────────────────────────────────────────────────────
# PUT /venues/update/{id}
# ───────────────────────────────────────────────────────────────

def test_update_venue_unauthenticated():
    response = client.put(f"/venues/update/{FAKE_ID}", json=venue_payload())
    assert response.status_code == 401

def test_update_venue_requires_admin():
    response = client.put(f"/venues/update/{FAKE_ID}", json=venue_payload(), headers=auth_headers())
    assert response.status_code == 403

def test_update_venue_not_found(admin_headers):
    response = client.put(f"/venues/update/{FAKE_ID}", json=venue_payload(), headers=admin_headers)
    assert response.status_code == 404

def test_update_venue_success(admin_headers):
    add_response = client.post("/venues/add", json=venue_payload(name="Old Name"), headers=admin_headers)
    venue_id = add_response.json()["id"]

    response = client.put(
        f"/venues/update/{venue_id}", json=venue_payload(name="Renamed Arena", total_capacity=9000),
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Arena"
    assert response.json()["total_capacity"] == 9000

# ───────────────────────────────────────────────────────────────
# DELETE /venues/delete/{id}
# ───────────────────────────────────────────────────────────────

def test_delete_venue_unauthenticated():
    response = client.delete(f"/venues/delete/{FAKE_ID}")
    assert response.status_code == 401

def test_delete_venue_requires_admin():
    response = client.delete(f"/venues/delete/{FAKE_ID}", headers=auth_headers())
    assert response.status_code == 403

def test_delete_venue_not_found(admin_headers):
    response = client.delete(f"/venues/delete/{FAKE_ID}", headers=admin_headers)
    assert response.status_code == 404

def test_delete_venue_success_then_not_found(admin_headers):
    add_response = client.post("/venues/add", json=venue_payload(name="Doomed Arena"), headers=admin_headers)
    venue_id = add_response.json()["id"]

    response = client.delete(f"/venues/delete/{venue_id}", headers=admin_headers)
    assert response.status_code == 200

    assert client.get(f"/venues/{venue_id}").status_code == 404
