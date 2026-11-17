import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.models.events import DirectSaleCampaign, Ticket, TicketType
from app.db.models.marketplace import Order, Payment, Product, ShippingStatus
from app.utils.tax import with_tax
from main import app

# ───────────────────────────────────────────────────────────────
# Capturing a PayPal payment whose goods are gone (bugs.md #31, #33), over real HTTP + Postgres.
# The fan approved on PayPal, but before we captured, the tier sold out, the product ran short, or
# the product was taken off sale. Nothing is captured, so no money moves: the payment fails, the
# ticket or order is released, and the endpoint answers 200 with status "failed" (before, a 404
# that left everything pending). PayPal is never called: create_order and capture_order are patched.
# Tests marked "Guard" pass already and pin down what must not change.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)
PAYMENT_SERVICE = "app.services.marketplace.payment_service"
COMPLETED = {"status": "COMPLETED"}


@pytest.fixture
def world(seed):
    company, venue = seed.company(), seed.venue()
    concert = seed.concert(company.id, venue.id)
    direct = seed.ticket_type(concert.id, sale_method="direct")
    now = datetime.now(timezone.utc)
    seed.save(DirectSaleCampaign(ticket_type_id=direct.id, sale_start_at=now - timedelta(days=1), sale_end_at=now + timedelta(days=30)))
    return {
        "seed": seed, "concert": concert, "direct": direct,
        "product": seed.product(seed.category().id, price=1000.0, quantity=10),
        "admin": seed.user("admin"), "fan": seed.user("fan"),
    }


def new_pg_order_id():
    return f"PAYPAL-{uuid.uuid4()}"


def paypal_creates(pg_order_id):
    approve = [{"rel": "approve", "href": "https://paypal.example/approve"}]
    return patch(f"{PAYMENT_SERVICE}.create_order", return_value={"id": pg_order_id, "links": approve})


def start_ticket_checkout(world, pg_order_id):
    seed = world["seed"]
    payload = {
        "ticket_type_id": str(world["direct"].id), "amount": with_tax(float(world["direct"].price)),
        "gateway": "paypal", "simulate_succ": None, "idempotency_key": str(uuid.uuid4()),
    }
    with paypal_creates(pg_order_id):
        res = client.post("/tickets/checkout", json=payload, headers=seed.headers(world["fan"]))
    assert res.status_code == 200, res.json()
    return uuid.UUID(res.json()["id"])


def start_order_checkout(world, pg_order_id, units=2):
    seed, fan, product = world["seed"], world["fan"], world["product"]
    headers = seed.headers(fan)
    assert client.post("/cart/add_cart", json={"product_id": str(product.id), "quantity": units}, headers=headers).status_code == 200
    payload = {
        "amount": with_tax(product.price * units), "shipping_address_id": str(seed.address(fan.id).id),
        "gateway": "paypal", "simulate_succ": None, "idempotency_key": str(uuid.uuid4()),
    }
    with paypal_creates(pg_order_id):
        res = client.post("/order/checkout", json=payload, headers=headers)
    assert res.status_code == 200, res.json()
    return uuid.UUID(res.json()["id"])


def capture(world, pg_order_id, paypal_response=COMPLETED):
    with patch(f"{PAYMENT_SERVICE}.capture_order", return_value=paypal_response) as paypal:
        res = client.post(f"/payment/paypal/capture/{pg_order_id}", headers=world["seed"].headers(world["fan"]))
    return res, paypal


def reload(seed, model, pk):
    seed.db.expire_all()
    return seed.db.get(model, pk)


def shipping_status_of(seed, order_id):
    seed.db.expire_all()
    return seed.db.query(ShippingStatus).filter(ShippingStatus.order_id == order_id).one().status.value


# ─── #31: stock is gone between approval and capture ───────────

def test_a_ticket_tier_that_sold_out_fails_the_payment_and_releases_the_ticket(world):
    seed, pg_order_id = world["seed"], new_pg_order_id()
    ticket_id = start_ticket_checkout(world, pg_order_id)
    tier = reload(seed, TicketType, world["direct"].id)
    tier.sold_quantity = tier.total_quantity  # other fans bought the rest meanwhile
    seed.db.commit()

    res, paypal = capture(world, pg_order_id)

    assert res.status_code == 200
    assert res.json()["status"] == "failed"
    paypal.assert_not_called()
    assert reload(seed, Ticket, ticket_id).status.value == "cancelled"
    assert reload(seed, TicketType, world["direct"].id).sold_quantity == tier.total_quantity
    # Resolved: capturing again finds nothing pending.
    assert capture(world, pg_order_id)[0].status_code == 404


def test_an_order_short_on_stock_fails_the_payment_and_cancels_the_order(world):
    seed, pg_order_id = world["seed"], new_pg_order_id()
    order_id = start_order_checkout(world, pg_order_id, units=2)
    product = reload(seed, Product, world["product"].id)
    product.quantity = 1  # someone else bought most of it meanwhile
    seed.db.commit()

    res, paypal = capture(world, pg_order_id)

    assert res.status_code == 200
    assert res.json()["status"] == "failed"
    paypal.assert_not_called()
    assert reload(seed, Order, order_id).status.value == "cancelled"
    assert shipping_status_of(seed, order_id) == "cancelled"
    assert reload(seed, Product, world["product"].id).quantity == 1


# ─── #33: the product was taken off sale ───────────────────────

def test_a_product_taken_off_sale_fails_the_payment_and_cancels_the_order(world):
    seed, pg_order_id = world["seed"], new_pg_order_id()
    order_id = start_order_checkout(world, pg_order_id, units=2)
    deactivated = client.delete(f"/products/delete/{world['product'].id}", headers=seed.headers(world["admin"]))
    assert deactivated.status_code == 200

    res, paypal = capture(world, pg_order_id)

    assert res.status_code == 200
    assert res.json()["status"] == "failed"
    paypal.assert_not_called()
    assert reload(seed, Order, order_id).status.value == "cancelled"
    assert shipping_status_of(seed, order_id) == "cancelled"
    assert reload(seed, Product, world["product"].id).quantity == 10


# ─── Guards ────────────────────────────────────────────────────

def test_an_order_with_stock_and_an_active_product_is_still_captured(world):
    # Guard
    seed, pg_order_id = world["seed"], new_pg_order_id()
    order_id = start_order_checkout(world, pg_order_id, units=2)

    res, paypal = capture(world, pg_order_id)

    assert res.status_code == 200
    assert res.json()["status"] == "success"
    paypal.assert_called_once()
    assert reload(seed, Order, order_id).status.value == "confirmed"
    assert reload(seed, Product, world["product"].id).quantity == 8


def test_a_ticket_with_seats_left_is_still_captured(world):
    # Guard
    seed, pg_order_id = world["seed"], new_pg_order_id()
    ticket_id = start_ticket_checkout(world, pg_order_id)

    res, _ = capture(world, pg_order_id)

    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert reload(seed, Ticket, ticket_id).status.value == "paid"
    assert reload(seed, TicketType, world["direct"].id).sold_quantity == 1


def test_a_lottery_win_is_still_captured_when_its_tier_is_fully_allocated(world):
    # Guard: the draw already counted a win's seat in sold_quantity, so a full tier is normal there.
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    lottery = seed.ticket_type(world["concert"].id, sale_method="lottery")
    lottery.sold_quantity = lottery.total_quantity
    seed.db.commit()
    won = seed.save(Ticket(
        ticket_type_id=lottery.id, user_id=fan.id, status="pending_payment",
        payment_deadline_at=datetime.now(timezone.utc) + timedelta(hours=48),
    ))
    seed.save(Payment(
        ticket_id=won.id, user_id=fan.id, amount=with_tax(float(lottery.price)), status="pending",
        payment_gateway="paypal", pg_order_id=pg_order_id, idempotency_key=uuid.uuid4(),
    ))

    res, _ = capture(world, pg_order_id)

    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert reload(seed, Ticket, won.id).status.value == "paid"


def test_a_declined_capture_still_fails_the_payment(world):
    # Guard: the existing path, unchanged.
    seed, pg_order_id = world["seed"], new_pg_order_id()
    order_id = start_order_checkout(world, pg_order_id)

    res, _ = capture(world, pg_order_id, paypal_response={"status": "DECLINED"})

    assert res.status_code == 200
    assert res.json()["status"] == "failed"
    assert reload(seed, Order, order_id).status.value == "cancelled"
