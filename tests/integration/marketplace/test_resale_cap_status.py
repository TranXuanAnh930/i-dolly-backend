import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.db.models.marketplace import Order
from app.services.marketplace.order_service import OrderService
from app.utils.resale import RESALE_CAP_QUANTITY
from app.utils.tax import with_tax
from main import app

# ───────────────────────────────────────────────────────────────
# The resale cap and order status (bugs.md #13). A fan may order RESALE_CAP_QUANTITY (3) units of a
# resale-capped product, ever. The cap counts the orders that still stand (confirmed, and pending,
# which reserves its units) and not cancelled ones: a declined payment, or a PayPal checkout the
# fan backed out of, no longer uses it up.
#
# It is enforced twice, and both must agree:
#   - OrderService._units_already_ordered, read by OrderService.checkout;
#   - the trigger function fn_enforce_resale_cap, the DB backstop.
# The helper and trigger tests below check one each; the end-to-end tests need both. Tests marked
# "Guard" pass already and must keep passing: they pin down what must NOT change.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)
PAYMENT_SERVICE = "app.services.marketplace.payment_service"


@pytest.fixture
def world(seed):
    """Two capped products, one uncapped, and two fans. Fans are created last so cleanup deletes
    them first, and with them every order made through the API."""
    capped_category = seed.category(is_resale_capped=True)
    return {
        "seed": seed,
        "capped": seed.product(capped_category.id, price=1000.0, quantity=50),
        "capped_2": seed.product(capped_category.id, price=1000.0, quantity=50),
        "uncapped": seed.product(seed.category().id, price=1000.0, quantity=50),
        "fan": seed.user("fan"),
        "other_fan": seed.user("fan"),
    }


def checkout(world, fan, product, units, gateway="mock", simulate_succ=True, pg_order_id=None):
    """Replace the fan's cart with `units` of `product` and check out."""
    seed = world["seed"]
    headers = seed.headers(fan)
    for item in client.get("/cart/see_cart", headers=headers).json()["items"]:
        client.delete(f"/cart/delete_cart/{item['id']}", headers=headers)
    assert client.post("/cart/add_cart", json={"product_id": str(product.id), "quantity": units}, headers=headers).status_code == 200
    payload = {
        "amount": with_tax(product.price * units), "shipping_address_id": str(seed.address(fan.id).id),
        "gateway": gateway, "simulate_succ": simulate_succ if gateway == "mock" else None,
        "idempotency_key": str(uuid.uuid4()),
    }
    if gateway == "paypal":
        approve = [{"rel": "approve", "href": "https://paypal.example/approve"}]
        with patch(f"{PAYMENT_SERVICE}.create_order", return_value={"id": pg_order_id, "links": approve}):
            return client.post("/order/checkout", json=payload, headers=headers)
    return client.post("/order/checkout", json=payload, headers=headers)


def status_of(seed, order_id):
    seed.db.expire_all()
    return seed.db.get(Order, uuid.UUID(order_id)).status.value


# ───────────────────────────────────────────────────────────────
# Piece 1: OrderService._units_already_ordered
# ───────────────────────────────────────────────────────────────

def test_helper_ignores_cancelled_orders(world):
    seed, fan, product = world["seed"], world["fan"], world["capped"]
    seed.order(fan.id, [(product, 1)], status="confirmed")
    seed.order(fan.id, [(product, 2)], status="cancelled")

    assert OrderService._units_already_ordered(seed.db, fan.id, {product.id}) == {product.id: 1}


def test_helper_counts_confirmed_and_pending_orders(world):
    # Guard: a pending order reserves its units.
    seed, fan, product = world["seed"], world["fan"], world["capped"]
    seed.order(fan.id, [(product, 1)], status="confirmed")
    seed.order(fan.id, [(product, 2)], status="pending")

    assert OrderService._units_already_ordered(seed.db, fan.id, {product.id}) == {product.id: 3}


def test_helper_is_per_buyer_and_per_product(world):
    # Guard
    seed, fan, other = world["seed"], world["fan"], world["other_fan"]
    seed.order(fan.id, [(world["capped"], 2)])
    seed.order(fan.id, [(world["capped_2"], 1)])
    seed.order(other.id, [(world["capped"], 3)])

    counts = OrderService._units_already_ordered(seed.db, fan.id, {world["capped"].id, world["capped_2"].id})

    assert counts == {world["capped"].id: 2, world["capped_2"].id: 1}
    assert OrderService._units_already_ordered(seed.db, fan.id, {world["uncapped"].id}) == {}


# ───────────────────────────────────────────────────────────────
# Piece 2: the trigger function. These insert order lines directly, so only the DB is involved.
# ───────────────────────────────────────────────────────────────

def test_trigger_ignores_cancelled_orders(world):
    seed, fan, product = world["seed"], world["fan"], world["capped"]
    seed.order(fan.id, [(product, RESALE_CAP_QUANTITY)], status="cancelled")

    seed.order(fan.id, [(product, RESALE_CAP_QUANTITY)], status="confirmed")  # must not raise


def test_trigger_counts_only_the_orders_that_still_stand(world):
    # The cancelled order goes first: the trigger checks every new line against the cap, even one
    # whose order is already cancelled (in real flows an order is cancelled after its lines exist).
    seed, fan, product = world["seed"], world["fan"], world["capped"]
    seed.order(fan.id, [(product, 3)], status="cancelled")
    seed.order(fan.id, [(product, 2)], status="confirmed")
    seed.order(fan.id, [(product, 1)], status="confirmed")  # 2 + 1 = 3: allowed

    with pytest.raises(DBAPIError):
        seed.order(fan.id, [(product, 1)], status="confirmed")  # 3 + 1 = 4: blocked
    seed.db.rollback()


def test_trigger_still_blocks_a_unit_over_the_cap(world):
    # Guard
    seed, fan, product = world["seed"], world["fan"], world["capped"]
    seed.order(fan.id, [(product, RESALE_CAP_QUANTITY)], status="confirmed")

    with pytest.raises(DBAPIError):
        seed.order(fan.id, [(product, 1)], status="confirmed")
    seed.db.rollback()


def test_trigger_counts_pending_orders(world):
    # Guard
    seed, fan, product = world["seed"], world["fan"], world["capped"]
    seed.order(fan.id, [(product, RESALE_CAP_QUANTITY)], status="pending")

    with pytest.raises(DBAPIError):
        seed.order(fan.id, [(product, 1)], status="confirmed")
    seed.db.rollback()


# ───────────────────────────────────────────────────────────────
# End to end through POST /order/checkout: needs piece 1 and piece 2
# ───────────────────────────────────────────────────────────────

def test_a_declined_payment_does_not_use_up_the_cap(world):
    fan, product = world["fan"], world["capped"]
    declined = checkout(world, fan, product, RESALE_CAP_QUANTITY, simulate_succ=False)
    assert declined.status_code == 200
    assert declined.json()["status"] == "cancelled"

    retry = checkout(world, fan, product, RESALE_CAP_QUANTITY)

    assert retry.status_code == 200, retry.json()
    assert retry.json()["status"] == "confirmed"


def test_an_abandoned_paypal_checkout_does_not_block_the_retry(world):
    seed, fan, product, pg_order_id = world["seed"], world["fan"], world["capped"], f"PAYPAL-{uuid.uuid4()}"
    abandoned = checkout(world, fan, product, 2, gateway="paypal", pg_order_id=pg_order_id)
    assert abandoned.status_code == 200
    assert abandoned.json()["status"] == "pending"

    retry = checkout(world, fan, product, 2)

    assert retry.status_code == 200, retry.json()
    assert retry.json()["status"] == "confirmed"
    assert status_of(seed, abandoned.json()["id"]) == "cancelled"


def test_confirmed_orders_still_count(world):
    # Guard
    fan, product = world["fan"], world["capped"]
    assert checkout(world, fan, product, 2).status_code == 200

    res = checkout(world, fan, product, 2)

    assert res.status_code == 400
    assert res.json()["code"] == "resale_cap_exceeded"


def test_a_pending_order_still_reserves_its_units(world):
    # Guard: seeded without a payment row, so nothing releases it at the next checkout.
    seed, fan, product = world["seed"], world["fan"], world["capped"]
    seed.order(fan.id, [(product, RESALE_CAP_QUANTITY)], status="pending")

    res = checkout(world, fan, product, 1)

    assert res.status_code == 400
    assert res.json()["code"] == "resale_cap_exceeded"


def test_exactly_the_cap_is_allowed(world):
    # Guard
    assert checkout(world, world["fan"], world["capped"], RESALE_CAP_QUANTITY).status_code == 200


def test_uncapped_products_have_no_limit(world):
    # Guard
    assert checkout(world, world["fan"], world["uncapped"], 5).status_code == 200


def test_another_fans_orders_do_not_count(world):
    # Guard
    seed = world["seed"]
    seed.order(world["other_fan"].id, [(world["capped"], RESALE_CAP_QUANTITY)], status="confirmed")

    assert checkout(world, world["fan"], world["capped"], RESALE_CAP_QUANTITY).status_code == 200
