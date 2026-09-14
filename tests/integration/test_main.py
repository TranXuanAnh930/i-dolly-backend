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

# ─────────────────────────────────────────────────────────────
# Fixtures — reset_rate_limits is shared, autouse, in
# tests/integration/conftest.py; every test module under this directory
# gets it automatically, no per-file import needed.
# ─────────────────────────────────────────────────────────────

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
    response = client.get("/cart/see_cart")
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
    response = client.get("/cart/see_cart")
    assert response.status_code == 401

def test_see_cart_empty():
    headers = auth_headers()
    response = client.get("/cart/see_cart", headers=headers)
    assert response.status_code in (200, 404)

def test_add_to_cart_unauthenticated():
    response = client.post("/cart/add_cart", json={"product_id": FAKE_ID, "quantity": 1})
    assert response.status_code == 401

def test_add_to_cart_nonexistent_product():
    headers = auth_headers()
    response = client.post("/cart/add_cart",
                           json={"product_id": FAKE_ID, "quantity": 1},
                           headers=headers)
    assert response.status_code == 404

def test_delete_cart_not_found():
    headers = auth_headers()
    response = client.delete(f"/cart/delete_cart/{FAKE_ID}", headers=headers)
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

# ─────────────────────────────────────────────────────────────
# Talent / Marketplace domain tests
#
# These tables (management_companies, groups, idols, idol_colors, positions,
# album_details, merch_details, genres) start empty in this test DB and no
# test here ever successfully creates a row in them — every mutating
# endpoint in this section is admin/manager-gated, and this suite has no way
# to bootstrap an admin/manager account through the public API (the one
# fan account it registers is deliberately the only role reachable purely
# over HTTP — see register_user/auth_headers above). So unlike
# products/cart/order above, these tests only reach the RBAC/wiring
# boundary (401 unauthenticated, 403 wrong role, 404 not-found/empty) —
# the actual create/update/delete behavior (scoping, soft-delete, dual-FK
# resolution, etc.) is covered at the service layer in
# tests/unit/test_services.py, where a mocked current_user can hold any
# role. Every "empty list -> 404" assertion below relies on these tables
# staying empty for the reason above; if that ever changes (e.g. seed data
# gets loaded into this DB) these specific assertions would need revisiting.
# Exception: idol_colors/positions/genres are lookup tables pre-populated by
# migration data (not app-created rows, see database-design.md), so this DB
# already has baseline rows in those three specifically — their "all" tests
# below assert 200 with content, not the 404-when-empty shape.
# ─────────────────────────────────────────────────────────────

# --- Management Companies ---

def test_list_companies_empty():
    response = client.get("/management_companies/all")
    assert response.status_code == 404

def test_get_company_not_found():
    response = client.get(f"/management_companies/{FAKE_ID}")
    assert response.status_code == 404

def test_add_company_unauthenticated():
    response = client.post("/management_companies/add", json={"name": "Nova Entertainment"})
    assert response.status_code == 401

def test_add_company_requires_admin():
    headers = auth_headers()
    response = client.post("/management_companies/add", json={"name": "Nova Entertainment"}, headers=headers)
    assert response.status_code == 403

def test_update_company_requires_admin():
    headers = auth_headers()
    response = client.put(f"/management_companies/update/{FAKE_ID}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403

def test_delete_company_requires_admin():
    headers = auth_headers()
    response = client.delete(f"/management_companies/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

# --- Idol Colors ---

def test_list_idol_colors():
    # Migration-seeded lookup table — never empty (see this section's header).
    response = client.get("/idol_colors/all")
    assert response.status_code == 200
    assert len(response.json()) > 0

def test_add_idol_color_unauthenticated():
    response = client.post("/idol_colors/add", json={"name": "Sakura Pink", "hex_code": "#FFB7C5"})
    assert response.status_code == 401

def test_add_idol_color_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post(
        "/idol_colors/add", json={"name": "Sakura Pink", "hex_code": "#FFB7C5"}, headers=headers
    )
    assert response.status_code == 403

def test_update_idol_color_requires_manager_or_admin():
    headers = auth_headers()
    response = client.put(
        f"/idol_colors/update/{FAKE_ID}", json={"name": "Sakura Pink", "hex_code": "#FFB7C5"}, headers=headers
    )
    assert response.status_code == 403

def test_delete_idol_color_requires_admin():
    headers = auth_headers()
    response = client.delete(f"/idol_colors/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

# --- Positions (+ idol_positions join table) ---

def test_list_positions():
    # Migration-seeded lookup table — never empty (see this section's header).
    response = client.get("/positions/all")
    assert response.status_code == 200
    assert len(response.json()) > 0

def test_add_position_unauthenticated():
    response = client.post("/positions/add", json={"name": "Center"})
    assert response.status_code == 401

def test_add_position_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post("/positions/add", json={"name": "Center"}, headers=headers)
    assert response.status_code == 403

def test_update_position_requires_manager_or_admin():
    headers = auth_headers()
    response = client.put(f"/positions/update/{FAKE_ID}", json={"name": "Center"}, headers=headers)
    assert response.status_code == 403

def test_delete_position_requires_admin():
    headers = auth_headers()
    response = client.delete(f"/positions/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

def test_assign_idol_position_unauthenticated():
    response = client.post(
        "/positions/idol_positions/assign", json={"idol_id": FAKE_ID, "position_id": FAKE_ID}
    )
    assert response.status_code == 401

def test_assign_idol_position_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post(
        "/positions/idol_positions/assign",
        json={"idol_id": FAKE_ID, "position_id": FAKE_ID},
        headers=headers,
    )
    assert response.status_code == 403

def test_list_idol_positions_for_idol_empty():
    response = client.get(f"/positions/idol_positions/idol/{FAKE_ID}")
    assert response.status_code == 404

def test_list_all_idol_positions_empty():
    response = client.get("/positions/idol_positions/all")
    assert response.status_code == 404

def test_set_idol_position_primary_requires_manager_or_admin():
    headers = auth_headers()
    response = client.put(
        f"/positions/idol_positions/{FAKE_ID}/{FAKE_ID}",
        params={"is_primary": True},
        headers=headers,
    )
    assert response.status_code == 403

def test_unassign_idol_position_requires_manager_or_admin():
    headers = auth_headers()
    response = client.delete(f"/positions/idol_positions/{FAKE_ID}/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

# --- Groups ---

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

# --- Idols ---

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

# --- Album Details ---

def test_list_album_details_empty():
    response = client.get("/album_details/all")
    assert response.status_code == 404

def test_get_album_detail_not_found():
    response = client.get(f"/album_details/{FAKE_ID}")
    assert response.status_code == 404

def test_add_album_detail_unauthenticated():
    response = client.post("/album_details/add", json={"product_id": FAKE_ID, "idol_id": FAKE_ID})
    assert response.status_code == 401

def test_add_album_detail_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post(
        "/album_details/add", json={"product_id": FAKE_ID, "idol_id": FAKE_ID}, headers=headers
    )
    assert response.status_code == 403

def test_update_album_detail_requires_manager_or_admin():
    headers = auth_headers()
    response = client.put(f"/album_details/update/{FAKE_ID}", json={"track_count": 10}, headers=headers)
    assert response.status_code == 403

def test_delete_album_detail_requires_manager_or_admin():
    headers = auth_headers()
    response = client.delete(f"/album_details/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

# --- Merch Details ---

def test_list_merch_details_empty():
    response = client.get("/merch_details/all")
    assert response.status_code == 404

def test_get_merch_detail_not_found():
    response = client.get(f"/merch_details/{FAKE_ID}")
    assert response.status_code == 404

def test_add_merch_detail_unauthenticated():
    response = client.post("/merch_details/add", json={"product_id": FAKE_ID, "group_id": FAKE_ID})
    assert response.status_code == 401

def test_add_merch_detail_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post(
        "/merch_details/add", json={"product_id": FAKE_ID, "group_id": FAKE_ID}, headers=headers
    )
    assert response.status_code == 403

def test_update_merch_detail_requires_manager_or_admin():
    headers = auth_headers()
    response = client.put(f"/merch_details/update/{FAKE_ID}", json={"edition": "Reissue"}, headers=headers)
    assert response.status_code == 403

def test_delete_merch_detail_requires_manager_or_admin():
    headers = auth_headers()
    response = client.delete(f"/merch_details/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

# --- Genres (+ album_genres join table) ---

def test_list_genres():
    # Migration-seeded lookup table — never empty (see this section's header).
    response = client.get("/genres/all")
    assert response.status_code == 200
    assert len(response.json()) > 0

def test_add_genre_unauthenticated():
    response = client.post("/genres/add", json={"name": "City Pop"})
    assert response.status_code == 401

def test_add_genre_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post("/genres/add", json={"name": "City Pop"}, headers=headers)
    assert response.status_code == 403

def test_delete_genre_requires_admin():
    headers = auth_headers()
    response = client.delete(f"/genres/delete/{FAKE_ID}", headers=headers)
    assert response.status_code == 403

def test_assign_genre_unauthenticated():
    response = client.post(
        "/genres/album_genres/assign", json={"product_id": FAKE_ID, "genre_id": FAKE_ID}
    )
    assert response.status_code == 401

def test_assign_genre_requires_manager_or_admin():
    headers = auth_headers()
    response = client.post(
        "/genres/album_genres/assign",
        json={"product_id": FAKE_ID, "genre_id": FAKE_ID},
        headers=headers,
    )
    assert response.status_code == 403

def test_list_album_genres_for_album_empty():
    response = client.get(f"/genres/album_genres/album/{FAKE_ID}")
    assert response.status_code == 404

def test_list_all_album_genres_empty():
    response = client.get("/genres/album_genres/all")
    assert response.status_code == 404

def test_unassign_genre_requires_manager_or_admin():
    headers = auth_headers()
    response = client.delete(f"/genres/album_genres/{FAKE_ID}/{FAKE_ID}", headers=headers)
    assert response.status_code == 403