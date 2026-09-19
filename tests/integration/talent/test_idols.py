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
# Idol Tests
# ───────────────────────────────────────────────────────────────

# This table starts empty in the test DB and no test here creates a row —
# every mutating endpoint is admin/manager-gated, and this suite has no way to
# bootstrap an admin/manager account through the public API (only the fan role
# is reachable over HTTP — see register_user/auth_headers above).
# So these tests only reach the RBAC/wiring boundary (401 unauthenticated, 403
# wrong role, 404 not-found/empty) — actual create/update/delete behavior
# (scoping, soft-delete, dual-FK resolution, etc.) is covered at the service
# layer in tests/unit/talent/test_idol_service.py, where a mocked
# current_user can hold any role.

def test_list_idols_empty():
    response = client.get("/idols/all")
    assert response.status_code == 404

def test_get_members_page_empty():
    response = client.get("/idols/members-page")
    assert response.status_code == 404

def test_get_manager_idols_page_never_404s():
    response = client.get("/idols/manager-idols-page")
    assert response.status_code == 200
    assert response.json() == {"idols": [], "groups": []}

def test_get_manager_idol_form_page_never_404s():
    response = client.get("/idols/manager-idol-form-page")
    assert response.status_code == 200
    data = response.json()
    # idols/groups are app-created rows (empty in this test DB); colors is
    # the migration-seeded idol_colors lookup table, never empty.
    assert data["idols"] == []
    assert data["groups"] == []
    assert len(data["colors"]) > 0

def test_get_idol_not_found():
    response = client.get(f"/idols/{FAKE_ID}")
    assert response.status_code == 404

def test_get_idol_detail_not_found():
    response = client.get(f"/idols/{FAKE_ID}/detail")
    assert response.status_code == 404

def test_add_idol_unauthenticated():
    # multipart/form-data, not JSON — see idols.py's add_new_idol.
    response = client.post("/idols/add", data={"name": "Test Idol", "company_id": FAKE_ID})
    assert response.status_code == 401

def test_add_idol_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post(
        "/idols/add", data={"name": "Test Idol", "company_id": FAKE_ID}, headers=headers
    )
    assert response.status_code == 403

def test_update_idol_requires_manager_or_admin():
    headers = auth_headers()
    response = client.put(f"/idols/update/{FAKE_ID}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403

def test_delete_idol_requires_manager_or_admin():
    headers = auth_headers()
    response = client.delete(f"/idols/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

def test_activate_idol_requires_manager_or_admin():
    headers = auth_headers()
    response = client.patch(f"/idols/activate/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

def test_upload_idol_image_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post(
        f"/idols/{FAKE_ID}/image",
        files={"image": ("t.png", b"fake-image-bytes", "image/png")},
        headers=headers,
    )
    assert response.status_code == 403
