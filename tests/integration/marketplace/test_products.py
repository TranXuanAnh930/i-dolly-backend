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
# Products Tests
# ───────────────────────────────────────────────────────────────

def test_get_all_products_unauthenticated():
    response = client.get("/products/all")
    assert response.status_code in (200, 404, 429)

def test_get_products_pagination():
    response = client.get("/products/pagination?page=1&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "page" in data
    assert "limit" in data
    assert "count" in data
    assert "data" in data

def test_get_products_filter_missing_category():
    response = client.get("/products/filter")
    assert response.status_code == 422

def test_get_products_filter_with_category():
    response = client.get("/products/filter?category=electronics")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data

def test_add_product_requires_admin():
    headers = auth_headers()
    payload = {
        "name": "Test Phone",
        "price": 9999.0,
        "description": "A test product",
        "quantity": 50,
        "category_id": FAKE_ID
    }
    response = client.post("/products/add_product", json=payload, headers=headers)
    assert response.status_code == 403

def test_add_product_unauthenticated():
    payload = {
        "name": "Test Phone",
        "price": 9999.0,
        "description": "A test product",
        "quantity": 50,
        "category_id": FAKE_ID
    }
    response = client.post("/products/add_product", json=payload)
    assert response.status_code == 401

def test_search_product_not_found():
    response = client.get(f"/products/search/{FAKE_ID}")
    assert response.status_code == 404

def test_delete_product_requires_admin():
    headers = auth_headers()
    response = client.delete(f"/products/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403
