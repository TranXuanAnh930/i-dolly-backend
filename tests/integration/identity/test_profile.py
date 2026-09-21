import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.identity import Users
from app.db.session import session as db_session
from app.utils.hashing import hash_password
from app.utils.jwt_manager import create_access_token, create_password_reset_token
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

# /profile/make-admin and /profile/create-manager are the only ways to mint a
# privileged account through the public API, and both require an existing
# admin (require_admin) — a fresh test DB has none, so the first one has to
# be minted directly via a real DB row, same as test_permissions.py's
# Factory. Not shared with that file on purpose — every integration module
# under this directory is self-contained (see conftest.py's own note).
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
    yield {"Authorization": f"Bearer {token}"}, admin.id
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

# ───────────────────────────────────────────────────────────────
# GET /profile/me
# ───────────────────────────────────────────────────────────────

def test_me_unauthenticated():
    response = client.get("/profile/me")
    assert response.status_code == 401

def test_me_success():
    response = client.get("/profile/me", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["email"] == "demo@example.com"

# ───────────────────────────────────────────────────────────────
# PUT /profile/change-password
# ───────────────────────────────────────────────────────────────

def test_change_password_unauthenticated():
    response = client.put("/profile/change-password", json={"old_password": "demo123", "new_password": "newpass123"})
    assert response.status_code == 401

def test_change_password_wrong_old_password():
    response = client.put(
        "/profile/change-password",
        json={"old_password": "wrongpass", "new_password": "newpass123"},
        headers=auth_headers(),
    )
    assert response.status_code == 400

def test_change_password_success_then_old_creds_rejected():
    email, old_password, new_password = f"changepw-{uuid.uuid4()}@example.com", "oldpass123", "newpass456"
    register_user(email=email, password=old_password)
    headers = auth_headers(email, old_password)

    response = client.put(
        "/profile/change-password",
        json={"old_password": old_password, "new_password": new_password},
        headers=headers,
    )
    assert response.status_code == 200

    assert login_user(email, old_password).status_code in (400, 401)
    assert login_user(email, new_password).status_code == 200

# ───────────────────────────────────────────────────────────────
# POST /profile/forgot-password / /profile/set-password
# ───────────────────────────────────────────────────────────────

def test_forgot_password_registered_and_unregistered_both_200():
    # Same generic response either way — the router's own comment says this
    # can't be used to enumerate accounts.
    assert client.post("/profile/forgot-password", json={"email": "demo@example.com"}).status_code == 200
    assert client.post("/profile/forgot-password", json={"email": "nobody@example.com"}).status_code == 200

def test_set_password_invalid_token():
    response = client.post("/profile/set-password", json={"token": "garbage-token", "new_password": "whatever123"})
    assert response.status_code == 401

def test_set_password_user_not_found():
    # A structurally valid reset token minted for an id no user has —
    # mirrors how AuthService.verify_email_token's own not-found path is
    # exercised, no way to reach it purely over HTTP.
    token = create_password_reset_token(uuid.uuid4())
    response = client.post("/profile/set-password", json={"token": token, "new_password": "whatever123"})
    assert response.status_code == 404

def test_set_password_success_then_login_with_new_password():
    email, old_password, new_password = f"resetpw-{uuid.uuid4()}@example.com", "oldpass123", "newpass789"
    register_response = register_user(email=email, password=old_password)
    user_id = register_response.json()["id"]

    token = create_password_reset_token(uuid.UUID(user_id))
    response = client.post("/profile/set-password", json={"token": token, "new_password": new_password})
    assert response.status_code == 200

    assert login_user(email, new_password).status_code == 200

# ───────────────────────────────────────────────────────────────
# POST /profile/logout
# ───────────────────────────────────────────────────────────────

def test_logout_no_cookie():
    response = client.post("/profile/logout")
    assert response.status_code == 401

def test_logout_invalid_token():
    response = client.post("/profile/logout", cookies={"refresh_token": "not-a-real-token"})
    assert response.status_code == 404

def test_logout_success():
    email, password = f"logout-{uuid.uuid4()}@example.com", "pass123"
    register_user(email=email, password=password)
    login_response = login_user(email, password)
    # The refresh_token cookie is set with secure=True — TestClient's cookie
    # jar won't replay a Secure cookie over the plain-http base_url it uses,
    # so it's extracted here and passed explicitly rather than relying on
    # the jar to carry it into the next request automatically.
    refresh_token = login_response.cookies.get("refresh_token")
    assert refresh_token

    response = client.post("/profile/logout", cookies={"refresh_token": refresh_token})
    assert response.status_code == 200

    # revoke_token matches by token string regardless of its current revoked
    # state, so logging out again with the same (already-revoked) token is
    # idempotent — still 200, not a 404 — rather than erroring on a token
    # that already did its job.
    response_again = client.post("/profile/logout", cookies={"refresh_token": refresh_token})
    assert response_again.status_code == 200

# ───────────────────────────────────────────────────────────────
# POST /profile/make-admin
# ───────────────────────────────────────────────────────────────

def test_make_admin_unauthenticated():
    response = client.post("/profile/make-admin", json={"user_id": "11111111-1111-1111-1111-111111111111"})
    assert response.status_code == 401

def test_make_admin_requires_admin():
    response = client.post(
        "/profile/make-admin", json={"user_id": "11111111-1111-1111-1111-111111111111"}, headers=auth_headers(),
    )
    assert response.status_code == 403

def test_make_admin_not_found(admin_headers):
    headers, _ = admin_headers
    response = client.post(
        "/profile/make-admin", json={"user_id": "11111111-1111-1111-1111-111111111111"}, headers=headers,
    )
    assert response.status_code == 404

def test_make_admin_promotes_role_not_just_the_deprecated_flag(admin_headers):
    """Regression test: promote_admin used to only ever set the deprecated
    is_admin column, never role — the column require_admin actually checks
    (database-design.md/architecture.md's own note that role is the source
    of truth). A promoted user's *existing* access token must immediately
    gain admin access, since role is read fresh from the DB per request,
    not baked into the token."""
    admin_auth_headers, _ = admin_headers
    email, password = f"promote-{uuid.uuid4()}@example.com", "pass123"
    register_response = register_user(email=email, password=password)
    fan_id = register_response.json()["id"]
    fan_headers = auth_headers(email, password)

    response = client.post("/profile/make-admin", json={"user_id": fan_id}, headers=admin_auth_headers)
    assert response.status_code == 200

    # The fan's own (already-issued, never refreshed) access token can now
    # reach an admin-gated route — proves role changed, not just is_admin.
    self_promote_again = client.post("/profile/make-admin", json={"user_id": fan_id}, headers=fan_headers)
    assert self_promote_again.status_code == 400  # "already admin" — was reachable only via role

def test_make_admin_already_admin(admin_headers):
    admin_auth_headers, admin_id = admin_headers
    response = client.post("/profile/make-admin", json={"user_id": str(admin_id)}, headers=admin_auth_headers)
    assert response.status_code == 400

# ───────────────────────────────────────────────────────────────
# POST /profile/create-manager
# ───────────────────────────────────────────────────────────────

FAKE_ID = "11111111-1111-1111-1111-111111111111"

def test_create_manager_unauthenticated():
    response = client.post("/profile/create-manager", json={
        "name": "Manager", "email": "newmanager@example.com", "password": "pass123", "company_id": FAKE_ID,
    })
    assert response.status_code == 401

def test_create_manager_requires_admin():
    response = client.post(
        "/profile/create-manager",
        json={"name": "Manager", "email": "newmanager@example.com", "password": "pass123", "company_id": FAKE_ID},
        headers=auth_headers(),
    )
    assert response.status_code == 403

def test_create_manager_company_not_found(admin_headers):
    headers, _ = admin_headers
    response = client.post(
        "/profile/create-manager",
        json={"name": "Manager", "email": f"mgr-{uuid.uuid4()}@example.com", "password": "pass123", "company_id": FAKE_ID},
        headers=headers,
    )
    assert response.status_code == 404

def test_create_manager_email_taken(admin_headers):
    headers, _ = admin_headers
    company_response = client.post(
        "/management_companies/add", json={"name": f"Company {uuid.uuid4()}"}, headers=headers,
    )
    company_id = company_response.json()["id"]

    try:
        response = client.post(
            "/profile/create-manager",
            json={"name": "Manager", "email": "demo@example.com", "password": "pass123", "company_id": company_id},
            headers=headers,
        )
        assert response.status_code == 400
    finally:
        client.delete(f"/management_companies/delete/{company_id}", headers=headers)

def test_create_manager_success(admin_headers):
    headers, _ = admin_headers
    company_response = client.post(
        "/management_companies/add", json={"name": f"Company {uuid.uuid4()}"}, headers=headers,
    )
    company_id = company_response.json()["id"]
    manager_email = f"newmgr-{uuid.uuid4()}@example.com"

    try:
        response = client.post(
            "/profile/create-manager",
            json={"name": "New Manager", "email": manager_email, "password": "pass123", "company_id": company_id},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "manager"
        assert data["company_id"] == company_id

        # The new manager can actually log in with the password they were created with.
        assert login_user(manager_email, "pass123").status_code == 200
    finally:
        # ManagementCompanyService.delete_company doesn't cascade the manager row (Users.company_id
        # is ON DELETE SET NULL, not CASCADE) — delete the manager directly rather than leave a
        # users row (unlike company_id, nothing else asserts the users table is empty, but leaving
        # dangling test data around isn't the goal either).
        db = db_session()
        manager = db.query(Users).filter(Users.email == manager_email).first()
        if manager:
            db.delete(manager)
            db.commit()
        db.close()
        client.delete(f"/management_companies/delete/{company_id}", headers=headers)
