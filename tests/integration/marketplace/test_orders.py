import uuid

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
# Order / Checkout / Shipping Tests
# ───────────────────────────────────────────────────────────────

def test_checkout_unauthenticated():
    payload = {
        "amount": 1000,
        "shipping_address_id": FAKE_ID,
        "gateway": "mock",
        "simulate_succ": True
    }
    response = client.post("/order/checkout", json=payload)
    assert response.status_code == 401

def test_checkout_empty_cart():
    headers = auth_headers()
    payload = {
        "amount": 1000,
        "shipping_address_id": FAKE_ID,
        "gateway": "mock",
        "simulate_succ": True,
        "idempotency_key": str(uuid.uuid4())
    }
    response = client.post("/order/checkout", json=payload, headers=headers)
    assert response.status_code in (400, 404)

def test_fetch_placed_orders_unauthenticated():
    response = client.get("/order/fetch_placed_order")
    assert response.status_code == 401

def test_fetch_placed_orders_empty():
    headers = auth_headers()
    response = client.get("/order/fetch_placed_order", headers=headers)
    assert response.status_code == 200
    assert response.json() == []

def test_cancel_nonexistent_order():
    headers = auth_headers()
    response = client.patch(f"/order/cancel/{FAKE_ID}", headers=headers)
    assert response.status_code == 404

def test_shipping_status_not_found():
    headers = auth_headers()
    response = client.get(f"/order/shipping_status/{FAKE_ID}", headers=headers)
    assert response.status_code == 404

def test_update_shipping_status_requires_admin():
    headers = auth_headers()
    response = client.patch(
        f"/order/update_shipping_status/{FAKE_ID}",
        params={"new_status": "processing"},
        headers=headers
    )
    assert response.status_code == 403
