import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.marketplace import ShippingStatus
from app.db.models.shared import Notification
from main import app

# ───────────────────────────────────────────────────────────────
# Post-checkout order lifecycle over real HTTP + Postgres: a fan cancelling, a manager shipping
# (company-scoped through album_details/merch_details), the admin shipping-status override, and
# the company-scoped manager orders page. Orders are seeded directly; checkout itself is covered
# by test_orders.py and test_orders_concurrency.py.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)


@pytest.fixture
def shop(seed):
    """Two companies, one product owned by each (via idol merch / group album), one ownerless
    product, a fan and a manager per company."""
    company_a, company_b = seed.company(), seed.company()
    category = seed.category()
    product_a = seed.product(category.id)
    seed.merch(product_a.id, idol_id=seed.idol(company_a.id).id)
    product_b = seed.product(category.id)
    seed.album(product_b.id, group_id=seed.group(company_b.id).id)
    ownerless = seed.product(category.id)
    return {
        "seed": seed,
        "company_a": company_a, "company_b": company_b,
        "product_a": product_a, "product_b": product_b, "ownerless": ownerless,
        "fan": seed.user("fan"),
        "manager_a": seed.user("manager", company_a.id),
        "manager_b": seed.user("manager", company_b.id),
        "admin": seed.user("admin"),
    }


def shipping_status_of(seed, order_id):
    seed.db.expire_all()
    return seed.db.query(ShippingStatus).filter(ShippingStatus.order_id == order_id).one().status.value


# ───────────────────────────────────────────────────────────────
# Fan: cancel + read shipping status
# ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["pending", "processing"])
def test_fan_cancels_unshipped_order(shop, status):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)], shipping_status=status)

    res = client.patch(f"/order/cancel/{order.id}", headers=seed.headers(shop["fan"]))

    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert shipping_status_of(seed, order.id) == "cancelled"


@pytest.mark.parametrize("status", ["shipped", "delivered", "cancelled"])
def test_fan_cannot_cancel_order_past_processing(shop, status):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)], shipping_status=status)

    res = client.patch(f"/order/cancel/{order.id}", headers=seed.headers(shop["fan"]))
    assert res.status_code == 400
    assert shipping_status_of(seed, order.id) == status


def test_fan_cannot_cancel_order_without_shipping_status(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)], shipping_status=None)

    assert client.patch(f"/order/cancel/{order.id}", headers=seed.headers(shop["fan"])).status_code == 400


def test_fan_cannot_cancel_someone_elses_order(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)])
    other_fan = seed.user("fan")

    res = client.patch(f"/order/cancel/{order.id}", headers=seed.headers(other_fan))
    assert res.status_code == 404
    assert shipping_status_of(seed, order.id) == "pending"


def test_fan_reads_own_shipping_status_only(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)], shipping_status="processing")

    own = client.get(f"/order/shipping_status/{order.id}", headers=seed.headers(shop["fan"]))
    assert own.status_code == 200
    assert own.json()["status"] == "processing"

    other = client.get(f"/order/shipping_status/{order.id}", headers=seed.headers(seed.user("fan")))
    assert other.status_code == 404


# ───────────────────────────────────────────────────────────────
# Manager "Ship" button
# ───────────────────────────────────────────────────────────────

def test_owning_manager_ships_order_and_fan_is_notified(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 2)], shipping_status="processing")

    res = client.patch(f"/order/{order.id}/ship", headers=seed.headers(shop["manager_a"]))

    assert res.status_code == 200
    assert shipping_status_of(seed, order.id) == "shipped"
    notes = seed.db.query(Notification).filter(Notification.order_id == order.id).all()
    assert [(n.user_id, n.type.value) for n in notes] == [(shop["fan"].id, "order_shipped")]


def test_other_company_manager_cannot_ship(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)])

    res = client.patch(f"/order/{order.id}/ship", headers=seed.headers(shop["manager_b"]))
    assert res.status_code == 403
    assert shipping_status_of(seed, order.id) == "pending"


def test_mixed_company_order_shippable_by_either_owning_manager(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1), (shop["product_b"], 1)])

    assert client.patch(f"/order/{order.id}/ship", headers=seed.headers(shop["manager_b"])).status_code == 200


def test_ownerless_product_order_shippable_by_any_manager(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["ownerless"], 1)])

    assert client.patch(f"/order/{order.id}/ship", headers=seed.headers(shop["manager_b"])).status_code == 200


def test_admin_ships_any_order(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_b"], 1)])

    assert client.patch(f"/order/{order.id}/ship", headers=seed.headers(shop["admin"])).status_code == 200


@pytest.mark.parametrize("status", ["shipped", "delivered", "cancelled"])
def test_cannot_ship_from_terminal_status(shop, status):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)], shipping_status=status)

    res = client.patch(f"/order/{order.id}/ship", headers=seed.headers(shop["admin"]))
    assert res.status_code == 400
    assert status in res.json()["detail"]


def test_cannot_ship_order_without_shipping_status(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)], shipping_status=None)

    res = client.patch(f"/order/{order.id}/ship", headers=seed.headers(shop["admin"]))
    assert res.status_code == 400
    assert "unknown" in res.json()["detail"]


def test_ship_missing_order_404(shop):
    seed = shop["seed"]
    assert client.patch(f"/order/{uuid.uuid4()}/ship", headers=seed.headers(shop["admin"])).status_code == 404


def test_fan_cannot_ship(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)])
    assert client.patch(f"/order/{order.id}/ship", headers=seed.headers(shop["fan"])).status_code == 403


# ───────────────────────────────────────────────────────────────
# Admin shipping-status override
# ───────────────────────────────────────────────────────────────

def test_admin_sets_any_shipping_status(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)], shipping_status="shipped")

    res = client.patch(
        f"/order/update_shipping_status/{order.id}", params={"new_status": "delivered"},
        headers=seed.headers(shop["admin"]),
    )
    assert res.status_code == 200
    assert shipping_status_of(seed, order.id) == "delivered"


def test_admin_cannot_revive_cancelled_order(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)], shipping_status="cancelled")

    res = client.patch(
        f"/order/update_shipping_status/{order.id}", params={"new_status": "shipped"},
        headers=seed.headers(shop["admin"]),
    )
    assert res.status_code == 400
    assert shipping_status_of(seed, order.id) == "cancelled"


def test_update_shipping_status_missing_order_404(shop):
    seed = shop["seed"]
    res = client.patch(
        f"/order/update_shipping_status/{uuid.uuid4()}", params={"new_status": "shipped"},
        headers=seed.headers(shop["admin"]),
    )
    assert res.status_code == 404


def test_manager_cannot_use_admin_override(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["product_a"], 1)])
    res = client.patch(
        f"/order/update_shipping_status/{order.id}", params={"new_status": "delivered"},
        headers=seed.headers(shop["manager_a"]),
    )
    assert res.status_code == 403


# ───────────────────────────────────────────────────────────────
# Manager orders page
# ───────────────────────────────────────────────────────────────

def manager_page(seed, user, **params):
    res = client.get("/order/manager-orders-page", params=params, headers=seed.headers(user))
    assert res.status_code == 200
    return res.json()


def page_orders(page, order_ids):
    """This test's orders from a page, keyed by id (other tests' orders may share the DB)."""
    return {o["id"]: o for o in page["data"] if o["id"] in {str(i) for i in order_ids}}


def test_manager_sees_only_own_company_line_items(shop):
    seed = shop["seed"]
    mixed = seed.order(shop["fan"].id, [(shop["product_a"], 2), (shop["product_b"], 1)])
    only_b = seed.order(shop["fan"].id, [(shop["product_b"], 1)])

    orders = page_orders(manager_page(seed, shop["manager_a"], limit=50), [mixed.id, only_b.id])

    assert set(orders) == {str(mixed.id)}
    items = orders[str(mixed.id)]["items"]
    assert [i["product_id"] for i in items] == [str(shop["product_a"].id)]
    assert orders[str(mixed.id)]["company_total"] == shop["product_a"].price * 2
    assert orders[str(mixed.id)]["buyer_email"] == shop["fan"].email


def test_manager_cannot_widen_scope_with_company_id_param(shop):
    seed = shop["seed"]
    only_b = seed.order(shop["fan"].id, [(shop["product_b"], 1)])

    page = manager_page(seed, shop["manager_a"], company_id=str(shop["company_b"].id), limit=50)
    assert page_orders(page, [only_b.id]) == {}


def test_manager_sees_ownerless_product_orders(shop):
    seed = shop["seed"]
    order = seed.order(shop["fan"].id, [(shop["ownerless"], 1)])

    assert str(order.id) in page_orders(manager_page(seed, shop["manager_b"], limit=50), [order.id])


def test_admin_sees_all_or_filters_by_company(shop):
    seed = shop["seed"]
    order_a = seed.order(shop["fan"].id, [(shop["product_a"], 1)])
    order_b = seed.order(shop["fan"].id, [(shop["product_b"], 1)])

    unfiltered = page_orders(manager_page(seed, shop["admin"], limit=50), [order_a.id, order_b.id])
    assert set(unfiltered) == {str(order_a.id), str(order_b.id)}

    filtered = page_orders(
        manager_page(seed, shop["admin"], company_id=str(shop["company_a"].id), limit=50), [order_a.id, order_b.id]
    )
    assert set(filtered) == {str(order_a.id)}


def test_manager_page_pagination(shop):
    seed = shop["seed"]
    for _ in range(3):
        seed.order(shop["fan"].id, [(shop["product_a"], 1)])

    first = manager_page(seed, shop["manager_a"], page=1, limit=2)
    second = manager_page(seed, shop["manager_a"], page=2, limit=2)
    assert first["count"] == 2
    assert {o["id"] for o in first["data"]}.isdisjoint({o["id"] for o in second["data"]})


def test_manager_page_forbidden_for_fans(shop):
    seed = shop["seed"]
    res = client.get("/order/manager-orders-page", headers=seed.headers(shop["fan"]))
    assert res.status_code == 403

