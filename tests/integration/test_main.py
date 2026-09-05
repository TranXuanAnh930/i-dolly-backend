import pytest
from tests.conftest import fake_redis
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# Ids are UUIDs now, not autoincrementing ints. None of these tests depend on
# a real row existing at this id — every one asserts 401/403 (auth/authz
# short-circuits before an id lookup happens) or 404 via this intentionally
# nonexistent sentinel. A plain int literal here would now fail path/body
# validation with 422 before ever reaching the logic these tests target.
FAKE_ID = "11111111-1111-1111-1111-111111111111"

# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_rate_limits():
    for key in fake_redis.scan_iter("rate:ip:*"):
        fake_redis.delete(key)
    for key in fake_redis.scan_iter("rate:user:*"):
        fake_redis.delete(key)
    yield

@pytest.fixture(autouse=True)
def ensure_user_exists():
    register_user()
    yield

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────
# Auth Tests
# ─────────────────────────────────────────────────────────────

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
    response = client.get("/Cart/see_cart")
    assert response.status_code == 401

# ─────────────────────────────────────────────────────────────
# Products Tests
# ─────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────
# Cart Tests
# ─────────────────────────────────────────────────────────────

def test_see_cart_unauthenticated():
    response = client.get("/Cart/see_cart")
    assert response.status_code == 401

def test_see_cart_empty():
    headers = auth_headers()
    response = client.get("/Cart/see_cart", headers=headers)
    assert response.status_code in (200, 404)

def test_add_to_cart_unauthenticated():
    response = client.post("/Cart/add_cart", json={"product_id": FAKE_ID, "quantity": 1})
    assert response.status_code == 401

def test_add_to_cart_nonexistent_product():
    headers = auth_headers()
    response = client.post("/Cart/add_cart",
                           json={"product_id": FAKE_ID, "quantity": 1},
                           headers=headers)
    assert response.status_code == 404

def test_delete_cart_not_found():
    headers = auth_headers()
    response = client.delete(f"/Cart/delete_cart/{FAKE_ID}", headers=headers)
    assert response.status_code == 404

# ─────────────────────────────────────────────────────────────
# Order / Checkout Tests
# ─────────────────────────────────────────────────────────────

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
        "simulate_succ": True
    }
    response = client.post("/order/checkout", json=payload, headers=headers)
    assert response.status_code in (400, 404)

def test_fetch_placed_orders_unauthenticated():
    response = client.get("/order/fetch_placed_order")
    assert response.status_code == 401

def test_fetch_placed_orders_empty():
    headers = auth_headers()
    response = client.get("/order/fetch_placed_order", headers=headers)
    assert response.status_code in (200, 404)

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