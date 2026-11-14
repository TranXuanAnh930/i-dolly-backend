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
# Abandoned PayPal checkouts (bugs.md #12, #27) over real HTTP + Postgres. Tests marked "Guard"
# pin down what the release must NOT touch: paid tickets, other fans, lottery wins, confirmed orders
# and captured payments.
#
#   A. A fan who checks out again releases their own unfinished PayPal checkout:
#      TicketService._release_stale_paypal_ticket, OrderService._release_stale_paypal_orders.
#   B. A fan who clicks "Cancel" on PayPal cancels it explicitly:
#      POST /payment/paypal/cancel/{pg_order_id} -> PaymentService.cancel_paypal_payment.
#   Both go through PaymentService.cancel_pending_paypal_payment.
#
# PayPal itself is never called: create_order and capture_order are patched.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)
PAYMENT_SERVICE = "app.services.marketplace.payment_service"


def paypal_creates(pg_order_id):
    """Patch PayPal's create-order call to return `pg_order_id`."""
    return patch(
        f"{PAYMENT_SERVICE}.create_order",
        return_value={"id": pg_order_id, "links": [{"rel": "approve", "href": "https://paypal.example/approve"}]},
    )


def new_pg_order_id():
    return f"PAYPAL-{uuid.uuid4()}"


@pytest.fixture
def world(seed):
    """A concert with a direct-sale tier on sale, a product, and two fans. Fans are created last so
    cleanup deletes them first, and with them every ticket, order and payment made through the API."""
    company, venue = seed.company(), seed.venue()
    concert = seed.concert(company.id, venue.id)
    direct = seed.ticket_type(concert.id, sale_method="direct")
    now = datetime.now(timezone.utc)
    seed.save(DirectSaleCampaign(ticket_type_id=direct.id, sale_start_at=now - timedelta(days=1), sale_end_at=now + timedelta(days=30)))
    product = seed.product(seed.category().id, price=1000.0, quantity=10)
    return {
        "seed": seed, "concert": concert, "direct": direct, "product": product,
        "fan": seed.user("fan"), "other_fan": seed.user("fan"),
    }


def reload(seed, model, pk):
    seed.db.expire_all()
    return seed.db.get(model, pk)


def payment_for(seed, pg_order_id) -> Payment:
    seed.db.expire_all()
    return seed.db.query(Payment).filter(Payment.pg_order_id == pg_order_id).one()


def buy_ticket(world, fan, gateway, pg_order_id=None):
    payload = {
        "ticket_type_id": str(world["direct"].id), "amount": with_tax(float(world["direct"].price)),
        "gateway": gateway, "simulate_succ": True if gateway == "mock" else None,
        "idempotency_key": str(uuid.uuid4()),
    }
    if gateway == "paypal":
        with paypal_creates(pg_order_id):
            return client.post("/tickets/checkout", json=payload, headers=world["seed"].headers(fan))
    return client.post("/tickets/checkout", json=payload, headers=world["seed"].headers(fan))


def place_order(world, fan, gateway, pg_order_id=None):
    """Put one unit of the product in the fan's cart (once) and check out."""
    seed, headers = world["seed"], world["seed"].headers(fan)
    if not client.get("/cart/see_cart", headers=headers).json()["items"]:
        assert client.post("/cart/add_cart", json={"product_id": str(world["product"].id), "quantity": 1}, headers=headers).status_code == 200
    payload = {
        "amount": with_tax(world["product"].price), "shipping_address_id": str(seed.address(fan.id).id),
        "gateway": gateway, "simulate_succ": True if gateway == "mock" else None,
        "idempotency_key": str(uuid.uuid4()),
    }
    if gateway == "paypal":
        with paypal_creates(pg_order_id):
            return client.post("/order/checkout", json=payload, headers=headers)
    return client.post("/order/checkout", json=payload, headers=headers)


def shipping_status_of(seed, order_id):
    seed.db.expire_all()
    return seed.db.query(ShippingStatus).filter(ShippingStatus.order_id == order_id).one().status.value


# ───────────────────────────────────────────────────────────────
# A. Tickets: checking out again releases the fan's own abandoned PayPal checkout
# ───────────────────────────────────────────────────────────────

def test_abandoned_paypal_ticket_is_released_by_the_next_checkout(world):
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    abandoned = buy_ticket(world, fan, "paypal", pg_order_id)
    assert abandoned.json()["status"] == "pending_payment"

    retry = buy_ticket(world, fan, "mock")

    assert retry.status_code == 200, retry.json()
    assert retry.json()["status"] == "paid"
    assert reload(seed, Ticket, uuid.UUID(abandoned.json()["id"])).status.value == "cancelled"
    assert payment_for(seed, pg_order_id).status.value == "cancelled"
    # A pending direct-sale ticket never counted as sold, so only the paid one does.
    assert reload(seed, TicketType, world["direct"].id).sold_quantity == 1


def test_a_released_paypal_order_can_no_longer_be_captured(world):
    # The fan approves the old PayPal order in another tab after checking out again: no charge.
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    buy_ticket(world, fan, "paypal", pg_order_id)
    assert buy_ticket(world, fan, "mock").status_code == 200

    with patch(f"{PAYMENT_SERVICE}.capture_order") as capture:
        res = client.post(f"/payment/paypal/capture/{pg_order_id}", headers=seed.headers(fan))

    assert res.status_code == 404
    capture.assert_not_called()


def test_a_second_paypal_attempt_replaces_the_first(world):
    seed, fan, first, second = world["seed"], world["fan"], new_pg_order_id(), new_pg_order_id()
    buy_ticket(world, fan, "paypal", first)

    retry = buy_ticket(world, fan, "paypal", second)

    assert retry.status_code == 200, retry.json()
    assert retry.json()["status"] == "pending_payment"
    assert payment_for(seed, first).status.value == "cancelled"
    assert payment_for(seed, second).status.value == "pending"


def test_a_paid_ticket_still_blocks_a_second_purchase(world):
    # Guard
    seed, fan = world["seed"], world["fan"]
    paid = buy_ticket(world, fan, "mock")
    assert paid.json()["status"] == "paid"

    again = buy_ticket(world, fan, "mock")

    assert again.status_code in (400, 409)
    assert reload(seed, Ticket, uuid.UUID(paid.json()["id"])).status.value == "paid"


def test_another_fans_pending_checkout_is_left_alone(world):
    # Guard
    seed, pg_order_id = world["seed"], new_pg_order_id()
    theirs = buy_ticket(world, world["other_fan"], "paypal", pg_order_id)

    assert buy_ticket(world, world["fan"], "mock").status_code == 200

    assert reload(seed, Ticket, uuid.UUID(theirs.json()["id"])).status.value == "pending_payment"
    assert payment_for(seed, pg_order_id).status.value == "pending"


def test_a_pending_lottery_win_is_not_released(world):
    # Guard. A lottery win holds a seat until its own payment deadline; a direct-sale checkout mustn't
    # cancel it, even when its payment is a pending PayPal one.
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    lottery = seed.ticket_type(world["concert"].id, sale_method="lottery")
    won = seed.save(Ticket(
        ticket_type_id=lottery.id, user_id=fan.id, status="pending_payment",
        payment_deadline_at=datetime.now(timezone.utc) + timedelta(hours=48),
    ))
    seed.save(Payment(
        ticket_id=won.id, user_id=fan.id, amount=with_tax(float(lottery.price)), status="pending",
        payment_gateway="paypal", pg_order_id=pg_order_id, idempotency_key=uuid.uuid4(),
    ))

    attempt = buy_ticket(world, fan, "mock")

    assert attempt.status_code in (400, 409)
    assert reload(seed, Ticket, won.id).status.value == "pending_payment"
    assert payment_for(seed, pg_order_id).status.value == "pending"


# ───────────────────────────────────────────────────────────────
# A. Orders: checking out again cancels the fan's own abandoned PayPal orders
# ───────────────────────────────────────────────────────────────

def test_abandoned_paypal_order_is_cancelled_by_the_next_checkout(world):
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    abandoned = place_order(world, fan, "paypal", pg_order_id)
    assert abandoned.json()["status"] == "pending"
    seed.track(Order, uuid.UUID(abandoned.json()["id"]))

    retry = place_order(world, fan, "mock")

    assert retry.status_code == 200, retry.json()
    seed.track(Order, uuid.UUID(retry.json()["id"]))
    assert retry.json()["status"] == "confirmed"
    old_id = uuid.UUID(abandoned.json()["id"])
    assert reload(seed, Order, old_id).status.value == "cancelled"
    assert payment_for(seed, pg_order_id).status.value == "cancelled"
    assert shipping_status_of(seed, old_id) == "cancelled"


def test_a_confirmed_order_is_not_touched_by_a_later_checkout(world):
    # Guard
    seed, fan = world["seed"], world["fan"]
    paid = place_order(world, fan, "mock")
    assert paid.json()["status"] == "confirmed"
    seed.track(Order, uuid.UUID(paid.json()["id"]))

    later = place_order(world, fan, "paypal", new_pg_order_id())
    seed.track(Order, uuid.UUID(later.json()["id"]))

    assert reload(seed, Order, uuid.UUID(paid.json()["id"])).status.value == "confirmed"
    assert shipping_status_of(seed, uuid.UUID(paid.json()["id"])) == "pending"


def test_a_cancelled_order_can_no_longer_be_captured(world):
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    abandoned = place_order(world, fan, "paypal", pg_order_id)
    seed.track(Order, uuid.UUID(abandoned.json()["id"]))
    retry = place_order(world, fan, "mock")
    seed.track(Order, uuid.UUID(retry.json()["id"]))

    with patch(f"{PAYMENT_SERVICE}.capture_order") as capture:
        res = client.post(f"/payment/paypal/capture/{pg_order_id}", headers=seed.headers(fan))

    assert res.status_code == 404
    capture.assert_not_called()
    # Stock went down once, for the order that was paid.
    assert reload(seed, Product, world["product"].id).quantity == 9


# ───────────────────────────────────────────────────────────────
# B. POST /payment/paypal/cancel/{pg_order_id}
# ───────────────────────────────────────────────────────────────

def test_cancel_requires_login():
    # Guard
    assert client.post(f"/payment/paypal/cancel/{new_pg_order_id()}").status_code == 401


def test_cancel_unknown_order_is_404(world):
    # Guard
    res = client.post(f"/payment/paypal/cancel/{new_pg_order_id()}", headers=world["seed"].headers(world["fan"]))
    assert res.status_code == 404


def test_cancel_a_ticket_checkout_then_buy_again(world):
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    pending = buy_ticket(world, fan, "paypal", pg_order_id)

    res = client.post(f"/payment/paypal/cancel/{pg_order_id}", headers=seed.headers(fan))

    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert reload(seed, Ticket, uuid.UUID(pending.json()["id"])).status.value == "cancelled"
    assert buy_ticket(world, fan, "mock").status_code == 200


def test_cancel_an_order_checkout(world):
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    pending = place_order(world, fan, "paypal", pg_order_id)
    order_id = uuid.UUID(pending.json()["id"])
    seed.track(Order, order_id)

    res = client.post(f"/payment/paypal/cancel/{pg_order_id}", headers=seed.headers(fan))

    assert res.status_code == 200
    assert reload(seed, Order, order_id).status.value == "cancelled"
    assert shipping_status_of(seed, order_id) == "cancelled"


def test_cannot_cancel_another_fans_checkout(world):
    # Guard
    seed, pg_order_id = world["seed"], new_pg_order_id()
    theirs = buy_ticket(world, world["other_fan"], "paypal", pg_order_id)

    res = client.post(f"/payment/paypal/cancel/{pg_order_id}", headers=seed.headers(world["fan"]))

    assert res.status_code == 404
    assert reload(seed, Ticket, uuid.UUID(theirs.json()["id"])).status.value == "pending_payment"
    assert payment_for(seed, pg_order_id).status.value == "pending"


def test_cancelling_twice_is_404_the_second_time(world):
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    buy_ticket(world, fan, "paypal", pg_order_id)

    assert client.post(f"/payment/paypal/cancel/{pg_order_id}", headers=seed.headers(fan)).status_code == 200
    assert client.post(f"/payment/paypal/cancel/{pg_order_id}", headers=seed.headers(fan)).status_code == 404


def test_cannot_cancel_a_captured_payment(world):
    # Guard
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    pending = buy_ticket(world, fan, "paypal", pg_order_id)
    with patch(f"{PAYMENT_SERVICE}.capture_order", return_value={"status": "COMPLETED"}):
        assert client.post(f"/payment/paypal/capture/{pg_order_id}", headers=seed.headers(fan)).status_code == 200

    res = client.post(f"/payment/paypal/cancel/{pg_order_id}", headers=seed.headers(fan))

    assert res.status_code == 404
    assert payment_for(seed, pg_order_id).status.value == "success"
    assert reload(seed, Ticket, uuid.UUID(pending.json()["id"])).status.value == "paid"


def test_cancelling_a_lottery_win_payment_keeps_the_ticket(world):
    # The payment is cancelled, but the win keeps its seat until its deadline: the fan can pay again.
    seed, fan, pg_order_id = world["seed"], world["fan"], new_pg_order_id()
    lottery = seed.ticket_type(world["concert"].id, sale_method="lottery")
    won = seed.save(Ticket(
        ticket_type_id=lottery.id, user_id=fan.id, status="pending_payment",
        payment_deadline_at=datetime.now(timezone.utc) + timedelta(hours=48),
    ))
    seed.save(Payment(
        ticket_id=won.id, user_id=fan.id, amount=with_tax(float(lottery.price)), status="pending",
        payment_gateway="paypal", pg_order_id=pg_order_id, idempotency_key=uuid.uuid4(),
    ))

    res = client.post(f"/payment/paypal/cancel/{pg_order_id}", headers=seed.headers(fan))

    assert res.status_code == 200
    assert payment_for(seed, pg_order_id).status.value == "cancelled"
    assert reload(seed, Ticket, won.id).status.value == "pending_payment"
