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
# Group Tests
# ───────────────────────────────────────────────────────────────

# This table starts empty in the test DB and no test here creates a row —
# every mutating endpoint is admin/manager-gated, and this suite has no way to
# bootstrap an admin/manager account through the public API (only the fan role
# is reachable over HTTP — see register_user/auth_headers above).
# So these tests only reach the RBAC/wiring boundary (401 unauthenticated, 403
# wrong role, 404 not-found/empty) — actual create/update/delete behavior
# (scoping, soft-delete, dual-FK resolution, etc.) is covered at the service
# layer in tests/unit/talent/test_group_service.py, where a mocked
# current_user can hold any role.

def test_list_groups_empty():
    response = client.get("/groups/all")
    assert response.status_code == 404

def test_get_groups_page_empty():
    response = client.get("/groups/groups-page")
    assert response.status_code == 404

def test_get_manager_groups_page_never_404s():
    # Manager/admin settings pages deliberately return an empty list rather
    # than 404 — a fresh company legitimately has zero groups yet.
    response = client.get("/groups/manager-groups-page")
    assert response.status_code == 200
    assert response.json() == {"groups": []}

def test_get_group_not_found():
    response = client.get(f"/groups/{FAKE_ID}")
    assert response.status_code == 404

def test_get_group_detail_not_found():
    response = client.get(f"/groups/{FAKE_ID}/detail")
    assert response.status_code == 404

def test_add_group_unauthenticated():
    response = client.post("/groups/add", json={"name": "Prism Sirens", "company_id": FAKE_ID})
    assert response.status_code == 401

def test_add_group_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post(
        "/groups/add", json={"name": "Prism Sirens", "company_id": FAKE_ID}, headers=headers
    )
    assert response.status_code == 403

def test_update_group_requires_manager_or_admin():
    headers = auth_headers()
    response = client.put(f"/groups/update/{FAKE_ID}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403

def test_delete_group_requires_manager_or_admin():
    headers = auth_headers()
    response = client.delete(f"/groups/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

def test_activate_group_requires_manager_or_admin():
    headers = auth_headers()
    response = client.patch(f"/groups/activate/{FAKE_ID}", headers=headers)
    assert response.status_code == 403
