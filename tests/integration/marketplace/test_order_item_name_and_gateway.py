import uuid
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.models.marketplace import Cart, Order, Payment
from app.utils.tax import with_tax
from main import app

# ───────────────────────────────────────────────────────────────
# bugs.md #34: fan order items carry the product name, even after the product is deactivated.
# bugs.md #36: a PayPal failure at checkout answers 502 payment_gateway_unavailable and leaves
# nothing behind.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)
PAYMENT_SERVICE = "app.services.marketplace.payment_service"


@pytest.fixture
def world(seed):
    return {
        "seed": seed,
        "product": seed.product(seed.category().id, price=1000.0, quantity=50),
        "fan": seed.user("fan"),
    }


def checkout(world, gateway="mock"):
    seed, fan, product = world["seed"], world["fan"], world["product"]
    headers = seed.headers(fan)
    assert client.post("/cart/add_cart", json={"product_id": str(product.id), "quantity": 1}, headers=headers).status_code == 200
    payload = {
        "amount": with_tax(product.price), "shipping_address_id": str(seed.address(fan.id).id),
        "gateway": gateway, "simulate_succ": True if gateway == "mock" else None,
        "idempotency_key": str(uuid.uuid4()),
    }
    return client.post("/order/checkout", json=payload, headers=headers)


def test_order_items_carry_the_product_name(world):
    seed, fan, product = world["seed"], world["fan"], world["product"]
    placed = checkout(world)
    assert placed.status_code == 200, placed.json()
    assert placed.json()["items"][0]["product_name"] == product.name

    listed = client.get("/order/fetch_placed_order", headers=seed.headers(fan)).json()
    single = client.get(f"/order/single_placed_order/{placed.json()['id']}", headers=seed.headers(fan)).json()

    assert listed[0]["items"][0]["product_name"] == product.name
    assert single["items"][0]["product_name"] == product.name


def test_the_name_survives_deactivating_the_product(world):
    seed, fan, product = world["seed"], world["fan"], world["product"]
    order_id = checkout(world).json()["id"]
    product.is_active = False
    seed.db.commit()

    single = client.get(f"/order/single_placed_order/{order_id}", headers=seed.headers(fan))

    assert single.status_code == 200
    assert single.json()["items"][0]["product_name"] == product.name


@pytest.mark.parametrize("error", [
    httpx.ConnectError("no route"),
    httpx.HTTPStatusError("401", request=httpx.Request("POST", "https://paypal.example"), response=httpx.Response(401)),
])
def test_a_paypal_failure_at_checkout_is_a_502_and_leaves_nothing(world, error):
    seed, fan = world["seed"], world["fan"]
    with patch(f"{PAYMENT_SERVICE}.create_order", side_effect=error):
        res = checkout(world, gateway="paypal")

    assert res.status_code == 502
    assert res.json()["code"] == "payment_gateway_unavailable"
    seed.db.expire_all()
    assert seed.db.query(Order).filter(Order.user_id == fan.id).count() == 0
    assert seed.db.query(Payment).filter(Payment.user_id == fan.id).count() == 0
    assert seed.db.query(Cart).filter(Cart.user_id == fan.id).count() == 1  # the cart is untouched
