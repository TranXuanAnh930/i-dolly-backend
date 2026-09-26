import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.models.events import Concert, DirectSaleCampaign, TicketType, Venue
from app.db.models.identity import Users
from app.db.models.talent import ManagementCompany
from app.db.session import session as db_session
from app.utils.hashing import hash_password
from app.utils.jwt_manager import create_access_token
from app.utils.tax import with_tax
from main import app

client = TestClient(app)

FAKE_ID = "11111111-1111-1111-1111-111111111111"

# ───────────────────────────────────────────────────────────────
# Fixtures — reset_rate_limits is shared, autouse, in
# tests/integration/conftest.py; every test module under this directory
# gets it automatically, no per-file import needed.
# ───────────────────────────────────────────────────────────────

# Thin direct-DB row builder, scoped down to just what payment tests need
# (a real ticket to pay for) — same shape as test_permissions.py's own
# Factory, not shared with it on purpose (every integration module under
# this directory is self-contained, see conftest.py's own note).
class _Factory:
    def __init__(self, db):
        self.db = db
        self.created = []

    def _save(self, obj):
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        self.created.append(obj)
        return obj

    def fan(self):
        user = Users(
            name="Fan", email=f"{uuid.uuid4()}@example.com",
            hashed_password=hash_password("pass123"), role="fan", is_verified=True,
        )
        return self._save(user)

    def token(self, user):
        tok = create_access_token({"sub": str(user.id)})
        return {"Authorization": f"Bearer {tok}"}

    def company(self):
        return self._save(ManagementCompany(name=f"Company {uuid.uuid4()}"))

    def venue(self):
        return self._save(Venue(name=f"Venue {uuid.uuid4()}", address="1 Main St", city="Tokyo", country="Japan", total_capacity=5000))

    def concert(self, company_id, venue_id):
        return self._save(Concert(
            company_id=company_id, venue_id=venue_id, title=f"Concert {uuid.uuid4()}",
            capacity=500, event_datetime=datetime.now(timezone.utc) + timedelta(days=60),
        ))

    def ticket_type(self, concert_id, price=50.0, total_quantity=10):
        return self._save(TicketType(concert_id=concert_id, tier="regular", price=price, total_quantity=total_quantity, sale_method="direct"))

    def direct_sale_campaign(self, ticket_type_id):
        now = datetime.now(timezone.utc)
        return self._save(DirectSaleCampaign(ticket_type_id=ticket_type_id, sale_start_at=now - timedelta(days=1), sale_end_at=now + timedelta(days=30)))


@pytest.fixture
def factory():
    db = db_session()
    f = _Factory(db)
    try:
        yield f
    finally:
        for obj in reversed(f.created):
            db.delete(obj)
        db.commit()
        db.close()

def _buy_ticket(factory, fan, gateway="mock", simulate_succ=True):
    """Full chain to a real, paid-or-declined Ticket + Payment row: a
    company/venue/concert/direct-sale ticket type/campaign, then an actual
    /tickets/checkout call — same shape as test_permissions.py's ticket
    checkout tests, scoped down to just what a payment needs behind it."""
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id)
    factory.direct_sale_campaign(tt.id)
    payload = {
        "ticket_type_id": str(tt.id),
        "amount": with_tax(float(tt.price)),
        "gateway": gateway,
        "simulate_succ": simulate_succ,
        "idempotency_key": str(uuid.uuid4()),
    }
    response = client.post("/tickets/checkout", json=payload, headers=factory.token(fan))
    assert response.status_code == 200, response.json()
    from app.db.models.events import Ticket
    factory.created.append(factory.db.get(Ticket, uuid.UUID(response.json()["id"])))
    return response.json()

# ───────────────────────────────────────────────────────────────
# PATCH /payment/status/all
# ───────────────────────────────────────────────────────────────

def test_status_all_unauthenticated():
    response = client.patch("/payment/status/all")
    assert response.status_code == 401

def test_status_all_none_found(factory):
    fan = factory.fan()
    response = client.patch("/payment/status/all", headers=factory.token(fan))
    assert response.status_code == 200
    assert response.json() == []

def test_status_all_found(factory):
    fan = factory.fan()
    with patch("app.services.marketplace.payment_service.create_order") as mock_create_order:
        _buy_ticket(factory, fan)
        mock_create_order.assert_not_called()  # mock gateway never calls PayPal

    response = client.patch("/payment/status/all", headers=factory.token(fan))
    assert response.status_code == 200
    assert len(response.json()) == 1

# ───────────────────────────────────────────────────────────────
# PATCH /payment/status/order/{order_id}
# ───────────────────────────────────────────────────────────────

def test_status_order_unauthenticated():
    response = client.patch(f"/payment/status/order/{FAKE_ID}")
    assert response.status_code == 401

def test_status_order_not_found(factory):
    fan = factory.fan()
    response = client.patch(f"/payment/status/order/{FAKE_ID}", headers=factory.token(fan))
    assert response.status_code == 404

# ───────────────────────────────────────────────────────────────
# PATCH /payment/status/ticket/{ticket_id}
# ───────────────────────────────────────────────────────────────

def test_status_ticket_unauthenticated():
    response = client.patch(f"/payment/status/ticket/{FAKE_ID}")
    assert response.status_code == 401

def test_status_ticket_not_found(factory):
    fan = factory.fan()
    response = client.patch(f"/payment/status/ticket/{FAKE_ID}", headers=factory.token(fan))
    assert response.status_code == 404

def test_status_ticket_not_mine_not_found(factory):
    owner = factory.fan()
    other_fan = factory.fan()
    ticket = _buy_ticket(factory, owner)

    response = client.patch(f"/payment/status/ticket/{ticket['id']}", headers=factory.token(other_fan))
    assert response.status_code == 404

def test_status_ticket_found(factory):
    fan = factory.fan()
    ticket = _buy_ticket(factory, fan)

    response = client.patch(f"/payment/status/ticket/{ticket['id']}", headers=factory.token(fan))
    assert response.status_code == 200
    assert response.json()["status"] == "success"

# ───────────────────────────────────────────────────────────────
# POST /payment/paypal/capture/{pg_order_id}
# ───────────────────────────────────────────────────────────────

def test_capture_unauthenticated():
    response = client.post(f"/payment/paypal/capture/{FAKE_ID}")
    assert response.status_code == 401

def test_capture_not_found(factory):
    fan = factory.fan()
    response = client.post(f"/payment/paypal/capture/{FAKE_ID}", headers=factory.token(fan))
    assert response.status_code == 404

def test_capture_success_resolves_pending_paypal_payment(factory):
    fan = factory.fan()
    pg_order_id = f"PAYPAL-{uuid.uuid4()}"
    with patch(
        "app.services.marketplace.payment_service.create_order",
        return_value={"id": pg_order_id, "links": [{"rel": "approve", "href": "https://paypal.example/approve"}]},
    ):
        ticket = _buy_ticket(factory, fan, gateway="paypal", simulate_succ=None)
    assert ticket["status"] == "pending_payment"

    with patch(
        "app.services.marketplace.payment_service.capture_order",
        return_value={"status": "COMPLETED"},
    ):
        response = client.post(f"/payment/paypal/capture/{pg_order_id}", headers=factory.token(fan))

    assert response.status_code == 200
    assert response.json()["status"] == "success"

def test_capture_not_yours_not_found(factory):
    owner = factory.fan()
    other_fan = factory.fan()
    pg_order_id = f"PAYPAL-{uuid.uuid4()}"
    with patch(
        "app.services.marketplace.payment_service.create_order",
        return_value={"id": pg_order_id, "links": [{"rel": "approve", "href": "https://paypal.example/approve"}]},
    ):
        _buy_ticket(factory, owner, gateway="paypal", simulate_succ=None)

    response = client.post(f"/payment/paypal/capture/{pg_order_id}", headers=factory.token(other_fan))
    assert response.status_code == 404

# ───────────────────────────────────────────────────────────────
# POST /payment/paypal/webhook
# ───────────────────────────────────────────────────────────────

def _webhook_payload(pg_order_id):
    return {"resource": {"supplementary_data": {"related_ids": {"order_id": pg_order_id}}}}

def test_webhook_bad_signature_rejected():
    with patch("app.router.marketplace.payment.verify_webhook_signature", return_value=False):
        response = client.post("/payment/paypal/webhook", json=_webhook_payload(FAKE_ID))
    assert response.status_code == 400

def test_webhook_resolves_pending_payment(factory):
    fan = factory.fan()
    pg_order_id = f"PAYPAL-{uuid.uuid4()}"
    with patch(
        "app.services.marketplace.payment_service.create_order",
        return_value={"id": pg_order_id, "links": [{"rel": "approve", "href": "https://paypal.example/approve"}]},
    ):
        _buy_ticket(factory, fan, gateway="paypal", simulate_succ=None)

    with patch("app.router.marketplace.payment.verify_webhook_signature", return_value=True), \
         patch("app.services.marketplace.payment_service.capture_order", return_value={"status": "COMPLETED"}):
        response = client.post("/payment/paypal/webhook", json=_webhook_payload(pg_order_id))

    assert response.status_code == 200

    status_response = client.patch("/payment/status/all", headers=factory.token(fan))
    assert status_response.json()[0]["status"] == "success"

def test_webhook_unresolvable_order_still_200():
    # PayPal calls this on its own schedule for every event, verified event
    # or not this app knows about — a non-2xx here just triggers a retry of
    # something that was never going to resolve to anything (the router's
    # own comment). Still 200 once the signature checks out.
    with patch("app.router.marketplace.payment.verify_webhook_signature", return_value=True):
        response = client.post("/payment/paypal/webhook", json=_webhook_payload(f"PAYPAL-{uuid.uuid4()}"))
    assert response.status_code == 200

@pytest.mark.parametrize("event", [
    {"event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "REFUND-1"}},
    {"event_type": "BILLING.PLAN.CREATED", "resource": {"id": "PLAN-1"}},
    {"event_type": "PAYMENT.CAPTURE.COMPLETED"},
])
def test_webhook_event_without_order_id_is_acknowledged(event):
    with patch("app.router.marketplace.payment.verify_webhook_signature", return_value=True), \
         patch("app.router.marketplace.payment.PaymentService.finalize_paypal_payment") as finalize:
        response = client.post("/payment/paypal/webhook", json=event)
    assert response.status_code == 200
    finalize.assert_not_called()

def test_webhook_order_approved_event_finalizes_by_resource_id():
    event = {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "PAYPAL-ORDER-7"}}
    with patch("app.router.marketplace.payment.verify_webhook_signature", return_value=True), \
         patch("app.router.marketplace.payment.PaymentService.finalize_paypal_payment") as finalize:
        response = client.post("/payment/paypal/webhook", json=event)
    assert response.status_code == 200
    assert finalize.call_args.args[1] == "PAYPAL-ORDER-7"
