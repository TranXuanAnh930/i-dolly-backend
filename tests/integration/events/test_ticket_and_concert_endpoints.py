import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.models.events import DirectSaleCampaign, Ticket
from app.db.models.shared import Notification
from app.utils.tax import with_tax
from main import app

# ───────────────────────────────────────────────────────────────
# HTTP-level error mapping for the ticket and concert routers (which service exception becomes
# which status code), plus the concert read pages and performer assignment. The checkout locking
# itself is covered by the service-level race tests in this directory; role gates for ticket
# add/update/delete are in tests/integration/test_permissions.py.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)
PRICE = 100.0


@pytest.fixture(autouse=True)
def no_celery():
    with patch("app.celery_app.celery_app.send_task") as send_task:
        yield send_task


@pytest.fixture
def event(seed):
    company, other_company = seed.company(), seed.company()
    concert = seed.concert(company.id, seed.venue().id)
    direct = seed.ticket_type(concert.id, sale_method="direct", price=PRICE)
    now = datetime.now(timezone.utc)
    seed.save(DirectSaleCampaign(
        ticket_type_id=direct.id, sale_start_at=now - timedelta(days=1), sale_end_at=now + timedelta(days=1),
        status="open",
    ))
    return {
        "seed": seed, "company": company, "other_company": other_company, "concert": concert, "direct": direct,
        "fan": seed.user("fan"),
        "manager": seed.user("manager", company.id),
        "other_manager": seed.user("manager", other_company.id),
        "admin": seed.user("admin"),
    }


def checkout(event, user, ticket_type_id=None, amount=None, key=None):
    return client.post("/tickets/checkout", headers=event["seed"].headers(user), json={
        "ticket_type_id": str(ticket_type_id or event["direct"].id),
        "amount": amount if amount is not None else with_tax(PRICE),
        "gateway": "mock", "simulate_succ": True, "idempotency_key": str(key or uuid.uuid4()),
    })


# ───────────────────────────────────────────────────────────────
# POST /tickets/checkout (direct sale)
# ───────────────────────────────────────────────────────────────

def test_checkout_amount_mismatch_400(event):
    assert checkout(event, event["fan"], amount=1).status_code == 400


def test_checkout_unknown_ticket_type_404(event):
    assert checkout(event, event["fan"], ticket_type_id=uuid.uuid4()).status_code == 404


def test_checkout_lottery_tier_400(event):
    lottery = event["seed"].ticket_type(event["concert"].id, sale_method="lottery", price=PRICE)
    res = checkout(event, event["fan"], ticket_type_id=lottery.id)
    assert res.status_code == 400
    assert "lottery" in res.json()["detail"]


def test_checkout_sold_out_400(event):
    seed = event["seed"]
    event["direct"].total_quantity = 1
    event["direct"].sold_quantity = 1
    seed.db.commit()
    assert checkout(event, event["fan"]).status_code == 400


def test_checkout_reused_idempotency_key_409(event):
    key = uuid.uuid4()
    assert checkout(event, event["fan"], key=key).status_code == 200
    second_fan = event["seed"].user("fan")
    assert checkout(event, second_fan, key=key).status_code == 409


def test_checkout_as_manager_403(event):
    assert checkout(event, event["manager"]).status_code == 403


def test_my_tickets(event):
    fan = event["fan"]
    assert client.get("/tickets/mine", headers=event["seed"].headers(fan)).status_code == 404

    bought = checkout(event, fan).json()
    mine = client.get("/tickets/mine", headers=event["seed"].headers(fan)).json()
    assert [t["id"] for t in mine] == [bought["id"]]


# ───────────────────────────────────────────────────────────────
# POST /tickets/{id}/checkout (lottery win)
# ───────────────────────────────────────────────────────────────

def won_ticket(event, user, status="pending_payment"):
    if "lottery" not in event:
        event["lottery"] = event["seed"].ticket_type(event["concert"].id, sale_method="lottery", price=PRICE)
    lottery = event["lottery"]
    return event["seed"].save(Ticket(
        ticket_type_id=lottery.id, user_id=user.id, status=status,
        payment_deadline_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))


def pay_won(event, user, ticket_id, amount=None):
    return client.post(f"/tickets/{ticket_id}/checkout", headers=event["seed"].headers(user), json={
        "amount": amount if amount is not None else with_tax(PRICE), "gateway": "mock", "simulate_succ": True,
        "idempotency_key": str(uuid.uuid4()),
    })


def test_pay_won_ticket(event, no_celery):
    ticket = won_ticket(event, event["fan"])
    res = pay_won(event, event["fan"], ticket.id)

    assert res.status_code == 200
    assert res.json()["status"] == "paid"
    no_celery.assert_called_once()


def test_pay_won_ticket_errors(event):
    fan = event["fan"]
    ticket = won_ticket(event, fan)

    assert pay_won(event, fan, uuid.uuid4()).status_code == 404
    assert pay_won(event, event["seed"].user("fan"), ticket.id).status_code == 404
    assert pay_won(event, fan, ticket.id, amount=1).status_code == 400

    holder = event["seed"].user("fan")
    paid = won_ticket(event, holder, status="paid")
    assert pay_won(event, holder, paid.id).status_code == 400


# ───────────────────────────────────────────────────────────────
# POST /tickets/add (admin manual issue)
# ───────────────────────────────────────────────────────────────

def add_ticket(event, user_id, ticket_type_id=None, lottery_entry_id=None):
    payload = {"ticket_type_id": str(ticket_type_id or event["direct"].id), "user_id": str(user_id)}
    if lottery_entry_id:
        payload["lottery_entry_id"] = str(lottery_entry_id)
    return client.post("/tickets/add", json=payload, headers=event["seed"].headers(event["admin"]))


def test_admin_add_ticket_errors(event):
    fan = event["fan"]
    assert add_ticket(event, fan.id, ticket_type_id=uuid.uuid4()).status_code == 404
    assert add_ticket(event, uuid.uuid4()).status_code == 404
    assert add_ticket(event, event["manager"].id).status_code == 403
    assert add_ticket(event, fan.id, lottery_entry_id=uuid.uuid4()).status_code == 404

    assert add_ticket(event, fan.id).status_code == 200
    assert add_ticket(event, fan.id).status_code == 400  # already holds a live ticket for this concert


# ───────────────────────────────────────────────────────────────
# Concert reads
# ───────────────────────────────────────────────────────────────

def test_concert_reads(event):
    concert = event["concert"]

    assert client.get(f"/concerts/{concert.id}").json()["id"] == str(concert.id)
    assert client.get(f"/concerts/{uuid.uuid4()}").status_code == 404
    assert str(concert.id) in {c["id"] for c in client.get("/concerts/all").json()}
    assert client.get("/concerts/events-page").status_code == 200
    manager_page = client.get("/concerts/manager-events-page", headers=event["seed"].headers(event["manager"]))
    assert str(concert.id) in {c["id"] for c in manager_page.json()["concerts"]}
    assert client.get(f"/concerts/{uuid.uuid4()}/detail").status_code == 404


def test_concert_detail_personalized_for_ticket_holder(event):
    fan = event["fan"]
    assert checkout(event, fan).status_code == 200

    guest = client.get(f"/concerts/{event['concert'].id}/detail").json()
    holder = client.get(f"/concerts/{event['concert'].id}/detail", headers=event["seed"].headers(fan)).json()
    other = client.get(f"/concerts/{event['concert'].id}/detail", headers=event["seed"].headers(event["seed"].user("fan"))).json()

    assert (guest["has_ticket"], holder["has_ticket"], other["has_ticket"]) == (False, True, False)
    assert [t["sold_quantity"] for t in holder["ticket_types"]] == [1]


# ───────────────────────────────────────────────────────────────
# Performers
# ───────────────────────────────────────────────────────────────

def assign(event, user, **ids):
    payload = {"concert_id": str(ids.pop("concert_id", event["concert"].id))}
    payload.update({k: str(v) for k, v in ids.items()})
    return client.post("/concerts/performers/assign", json=payload, headers=event["seed"].headers(user))


def test_assign_and_remove_performer(event):
    seed, concert = event["seed"], event["concert"]
    idol = seed.idol(event["company"].id)
    group = seed.group(event["company"].id)
    assert client.get(f"/concerts/performers/concert/{concert.id}").status_code == 404

    idol_link = assign(event, event["manager"], idol_id=idol.id)
    group_link = assign(event, event["manager"], group_id=group.id)
    assert (idol_link.status_code, group_link.status_code) == (200, 200)

    listed = client.get(f"/concerts/performers/concert/{concert.id}").json()
    assert {p["id"] for p in listed} == {idol_link.json()["id"], group_link.json()["id"]}
    assert idol_link.json()["id"] in {p["id"] for p in client.get("/concerts/performers/all").json()}

    link_id = idol_link.json()["id"]
    assert client.delete(f"/concerts/performers/{link_id}", headers=seed.headers(event["other_manager"])).status_code == 403
    assert client.delete(f"/concerts/performers/{link_id}", headers=seed.headers(event["manager"])).status_code == 200
    assert client.delete(f"/concerts/performers/{link_id}", headers=seed.headers(event["manager"])).status_code == 404


def test_assign_performer_errors(event):
    idol = event["seed"].idol(event["company"].id)
    group = event["seed"].group(event["company"].id)

    assert assign(event, event["admin"]).status_code == 400
    assert assign(event, event["admin"], idol_id=idol.id, group_id=group.id).status_code == 400
    assert assign(event, event["admin"], concert_id=uuid.uuid4(), idol_id=idol.id).status_code == 404
    assert assign(event, event["other_manager"], idol_id=idol.id).status_code == 403
    assert assign(event, event["admin"], idol_id=uuid.uuid4()).status_code == 404
    assert assign(event, event["admin"], group_id=uuid.uuid4()).status_code == 404


# ───────────────────────────────────────────────────────────────
# Lottery draw trigger (the draw itself runs in Celery; see test_lottery_concurrency.py)
# ───────────────────────────────────────────────────────────────

def test_draw_trigger_enqueues_task_and_notifies_managers(event, no_celery):
    seed, concert = event["seed"], event["concert"]
    res = client.put(f"/concerts/lottery-draw/{concert.id}", headers=seed.headers(event["manager"]))

    assert res.status_code == 200
    no_celery.assert_called_once_with("app.tasks.lottery.draw_lottery", args=[str(concert.id), str(event["manager"].id)])
    notified = seed.db.query(Notification.user_id).filter(Notification.concert_id == concert.id).all()
    assert (event["manager"].id,) in notified


def test_draw_trigger_missing_concert_404(event):
    assert client.put(f"/concerts/lottery-draw/{uuid.uuid4()}", headers=event["seed"].headers(event["admin"])).status_code == 404


def test_manager_events_page_scoped_to_own_company(event):
    seed = event["seed"]
    other_concert = seed.concert(event["other_company"].id, seed.venue().id)
    ours = {str(event["concert"].id), str(other_concert.id)}

    def page(user):
        res = client.get("/concerts/manager-events-page", headers=seed.headers(user))
        assert res.status_code == 200
        return res.json()

    manager_page = page(event["manager"])
    assert {c["id"] for c in manager_page["concerts"]} & ours == {str(event["concert"].id)}
    # Venues are shared, so every venue stays available to the venue picker.
    assert str(other_concert.venue_id) in {v["id"] for v in manager_page["venues"]}
    assert {c["id"] for c in page(event["admin"])["concerts"]} & ours == ours
