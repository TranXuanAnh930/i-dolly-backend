"""Integration tests for RBAC/company-scoping across the real HTTP + DB
stack: role gates (require_manager_or_admin), a manager's own-company
scoping (_manager_scope_violation), and the manager-lock business rules
added on top of it — ticket/product price locks, and the event-open
capacity/date locks on concerts and ticket types.

Fixture rows (companies/users/venues/concerts/...) are inserted directly
via a real DB session rather than through the API — there's no endpoint to
self-register as a manager or admin (by design, database-design.md §4:
that's a platform-level action), so tests mint their own users and JWTs
directly, then exercise every actual permission check through real HTTP
requests against the running app.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.models.events import (
    Concert,
    DirectSaleCampaign,
    LotteryCampaign,
    LotteryEntry,
    LotteryPreference,
    Ticket,
    TicketType,
    Venue,
)
from app.db.models.identity import Users
from app.db.models.marketplace import Category, MerchDetail, Product
from app.db.models.talent import Idol, ManagementCompany
from app.db.session import session as db_session
from app.utils.hashing import hash_password
from app.utils.jwt_manager import create_access_token
from app.utils.tax import with_tax
from main import app

client = TestClient(app)

# reset_rate_limits is shared, autouse, in tests/integration/conftest.py —
# applies to every test module under this directory automatically.


class Factory:
    """Thin direct-DB row builder for fixture data, with FK-safe teardown
    (children deleted before their parents, i.e. reverse creation order)."""

    def __init__(self, db):
        self.db = db
        self.created = []

    def _save(self, obj):
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        self.created.append(obj)
        return obj

    def company(self):
        return self._save(ManagementCompany(name=f"Company {uuid.uuid4()}"))

    def user(self, role="fan", company_id=None):
        user = Users(
            name="Test User",
            email=f"{uuid.uuid4()}@example.com",
            hashed_password=hash_password("password123"),
            role=role,
            company_id=company_id,
            is_verified=True,
        )
        return self._save(user)

    def token(self, user):
        tok = create_access_token({"sub": str(user.id)})
        return {"Authorization": f"Bearer {tok}"}

    def venue(self):
        return self._save(Venue(
            name=f"Venue {uuid.uuid4()}", address="1 Main St", city="Tokyo",
            country="Japan", total_capacity=5000,
        ))

    def concert(self, company_id, venue_id, status=None, capacity=500, event_datetime=None, doors_open_at=None):
        concert = Concert(
            company_id=company_id, venue_id=venue_id, title=f"Concert {uuid.uuid4()}",
            capacity=capacity,
            event_datetime=event_datetime or (datetime.now(timezone.utc) + timedelta(days=60)),
            doors_open_at=doors_open_at,
        )
        if status is not None:
            concert.status = status
        return self._save(concert)

    def ticket_type(self, concert_id, tier="regular", price=50.0, total_quantity=100, sale_method="direct"):
        return self._save(TicketType(
            concert_id=concert_id, tier=tier, price=price,
            total_quantity=total_quantity, sale_method=sale_method,
        ))

    def category(self):
        return self._save(Category(name=f"Category {uuid.uuid4()}"))

    def product(self, category_id, price=999.0):
        return self._save(Product(
            name=f"Product {uuid.uuid4()}", price=price, description="A product",
            quantity=10, category_id=category_id,
        ))

    def idol(self, company_id):
        return self._save(Idol(company_id=company_id, name=f"Idol {uuid.uuid4()}"))

    def merch_detail(self, product_id, idol_id):
        return self._save(MerchDetail(product_id=product_id, idol_id=idol_id))

    def direct_sale_campaign(self, ticket_type_id, sale_start_at=None, sale_end_at=None, status="open"):
        now = datetime.now(timezone.utc)
        campaign = DirectSaleCampaign(
            ticket_type_id=ticket_type_id,
            sale_start_at=sale_start_at or (now - timedelta(days=1)),
            sale_end_at=sale_end_at or (now + timedelta(days=30)),
        )
        campaign.status = status
        return self._save(campaign)

    def lottery_campaign(self, ticket_type_id, entry_start_at=None, entry_end_at=None, status="open"):
        now = datetime.now(timezone.utc)
        campaign = LotteryCampaign(
            ticket_type_id=ticket_type_id,
            entry_start_at=entry_start_at or (now - timedelta(days=2)),
            entry_end_at=entry_end_at or (now + timedelta(days=5)),
        )
        campaign.status = status
        return self._save(campaign)

    def lottery_preference(self, concert_id, user_id, ticket_type_id, rank=1):
        return self._save(LotteryPreference(
            concert_id=concert_id, user_id=user_id, ticket_type_id=ticket_type_id, rank=rank,
        ))

    def lottery_entry(self, campaign_id, user_id, status="pending"):
        entry = LotteryEntry(campaign_id=campaign_id, user_id=user_id)
        entry.status = status
        return self._save(entry)


@pytest.fixture
def factory():
    db = db_session()
    f = Factory(db)
    try:
        yield f
    finally:
        for obj in reversed(f.created):
            db.delete(obj)
        db.commit()
        db.close()


def concert_payload(company_id, venue_id, **overrides):
    payload = {
        "company_id": str(company_id),
        "venue_id": str(venue_id),
        "title": "New Concert",
        "capacity": 500,
        "event_datetime": (datetime.now(timezone.utc) + timedelta(days=60)).isoformat(),
        "doors_open_at": None,
    }
    payload.update(overrides)
    return payload


def concert_update_payload(concert, **overrides):
    payload = {
        "venue_id": str(concert.venue_id),
        "title": concert.title,
        "description": concert.description,
        "capacity": concert.capacity,
        "event_datetime": concert.event_datetime.isoformat(),
        "doors_open_at": concert.doors_open_at.isoformat() if concert.doors_open_at else None,
    }
    payload.update(overrides)
    return payload


def product_payload(product, **overrides):
    payload = {
        "name": product.name,
        "price": product.price,
        "description": product.description,
        "quantity": product.quantity,
        "category_id": str(product.category_id),
    }
    payload.update(overrides)
    return payload


def direct_sale_campaign_payload(ticket_type_id, **overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "ticket_type_id": str(ticket_type_id),
        "sale_start_at": (now - timedelta(days=1)).isoformat(),
        "sale_end_at": (now + timedelta(days=30)).isoformat(),
    }
    payload.update(overrides)
    return payload


def lottery_campaign_payload(ticket_type_id, **overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "ticket_type_id": str(ticket_type_id),
        "entry_start_at": (now - timedelta(days=2)).isoformat(),
        "entry_end_at": (now + timedelta(days=5)).isoformat(),
    }
    payload.update(overrides)
    return payload


FAKE_ID = "11111111-1111-1111-1111-111111111111"


# ─────────────────────────────────────────────────────────────
# Concerts — role gate + company scoping
# ─────────────────────────────────────────────────────────────

def test_add_concert_unauthenticated(factory):
    company = factory.company()
    venue = factory.venue()
    response = client.post("/concerts/add", json=concert_payload(company.id, venue.id))
    assert response.status_code == 401


def test_add_concert_fan_forbidden(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    response = client.post("/concerts/add", json=concert_payload(company.id, venue.id), headers=factory.token(fan))
    assert response.status_code == 403


def test_add_concert_manager_wrong_company_forbidden(factory):
    owning_company = factory.company()
    other_company = factory.company()
    manager = factory.user(role="manager", company_id=other_company.id)
    venue = factory.venue()
    response = client.post(
        "/concerts/add", json=concert_payload(owning_company.id, venue.id), headers=factory.token(manager)
    )
    assert response.status_code == 403


def test_add_concert_manager_own_company_allowed(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    response = client.post("/concerts/add", json=concert_payload(company.id, venue.id), headers=factory.token(manager))
    assert response.status_code == 200
    assert response.json()["company_id"] == str(company.id)

    # Created via the API, not the factory — register it for teardown so it
    # gets deleted before the company/venue it FKs to (reversed(created)
    # order needs it last-in here, i.e. deleted first).
    factory.created.append(factory.db.get(Concert, uuid.UUID(response.json()["id"])))


def test_update_concert_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    response = client.put(
        f"/concerts/update/{concert.id}", json=concert_update_payload(concert, title="Hijacked"),
        headers=factory.token(other_manager),
    )
    assert response.status_code == 403


def test_update_concert_own_company_manager_allowed(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="scheduled")
    response = client.put(
        f"/concerts/update/{concert.id}", json=concert_update_payload(concert, title="Renamed Concert"),
        headers=factory.token(manager),
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed Concert"


def test_delete_concert_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    response = client.delete(f"/concerts/delete/{concert.id}", headers=factory.token(other_manager))
    assert response.status_code == 403


def test_delete_concert_soft_deletes_own_company(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="scheduled")
    response = client.delete(f"/concerts/delete/{concert.id}", headers=factory.token(manager))
    assert response.status_code == 200

    fetched = client.get(f"/concerts/{concert.id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "cancelled"


# ─────────────────────────────────────────────────────────────
# Concerts — manager lock once open to the public (event_locked)
# ─────────────────────────────────────────────────────────────

def test_update_concert_date_locked_for_manager_once_on_sale(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="on_sale")
    new_date = (datetime.now(timezone.utc) + timedelta(days=120)).isoformat()
    response = client.put(
        f"/concerts/update/{concert.id}", json=concert_update_payload(concert, event_datetime=new_date),
        headers=factory.token(manager),
    )
    assert response.status_code == 403
    assert "cancel" in response.json()["detail"].lower()


def test_update_concert_capacity_locked_for_manager_once_on_sale(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="on_sale", capacity=500)
    response = client.put(
        f"/concerts/update/{concert.id}", json=concert_update_payload(concert, capacity=800),
        headers=factory.token(manager),
    )
    assert response.status_code == 403


def test_update_concert_date_and_capacity_editable_by_admin_once_on_sale(factory):
    company = factory.company()
    admin = factory.user(role="admin")
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="on_sale", capacity=500)
    new_date = (datetime.now(timezone.utc) + timedelta(days=120)).isoformat()
    response = client.put(
        f"/concerts/update/{concert.id}",
        json=concert_update_payload(concert, event_datetime=new_date, capacity=800),
        headers=factory.token(admin),
    )
    assert response.status_code == 200
    assert response.json()["capacity"] == 800


def test_update_concert_date_editable_for_manager_while_scheduled(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="scheduled")
    new_date = (datetime.now(timezone.utc) + timedelta(days=120)).isoformat()
    response = client.put(
        f"/concerts/update/{concert.id}", json=concert_update_payload(concert, event_datetime=new_date),
        headers=factory.token(manager),
    )
    assert response.status_code == 200


def test_update_concert_date_editable_for_manager_after_cancel(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="on_sale")

    cancel = client.delete(f"/concerts/delete/{concert.id}", headers=factory.token(manager))
    assert cancel.status_code == 200

    new_date = (datetime.now(timezone.utc) + timedelta(days=120)).isoformat()
    response = client.put(
        f"/concerts/update/{concert.id}", json=concert_update_payload(concert, event_datetime=new_date),
        headers=factory.token(manager),
    )
    assert response.status_code == 200


# ─────────────────────────────────────────────────────────────
# Ticket types — role gate, company scoping, price/capacity locks
# ─────────────────────────────────────────────────────────────

def test_add_ticket_type_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    response = client.post(
        "/ticket_types/add",
        json={"concert_id": str(concert.id), "tier": "vip", "price": 100.0, "total_quantity": 50, "sale_method": "direct"},
        headers=factory.token(other_manager),
    )
    assert response.status_code == 403


def test_update_ticket_type_price_locked_for_manager(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="scheduled")
    ticket_type = factory.ticket_type(concert.id, price=50.0)

    response = client.put(
        f"/ticket_types/update/{ticket_type.id}", json={"price": 75.0},
        headers=factory.token(manager),
    )
    assert response.status_code == 403
    assert "price" in response.json()["detail"].lower()


def test_update_ticket_type_price_editable_by_admin(factory):
    company = factory.company()
    admin = factory.user(role="admin")
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="scheduled")
    ticket_type = factory.ticket_type(concert.id, price=50.0)

    response = client.put(
        f"/ticket_types/update/{ticket_type.id}", json={"price": 75.0},
        headers=factory.token(admin),
    )
    assert response.status_code == 200
    assert float(response.json()["price"]) == 75.0


def test_update_ticket_type_capacity_locked_for_manager_once_on_sale(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="on_sale")
    ticket_type = factory.ticket_type(concert.id, total_quantity=100)

    response = client.put(
        f"/ticket_types/update/{ticket_type.id}", json={"total_quantity": 200},
        headers=factory.token(manager),
    )
    assert response.status_code == 403


def test_update_ticket_type_capacity_editable_for_manager_while_scheduled(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id, status="scheduled")
    ticket_type = factory.ticket_type(concert.id, total_quantity=100)

    response = client.put(
        f"/ticket_types/update/{ticket_type.id}", json={"total_quantity": 200},
        headers=factory.token(manager),
    )
    assert response.status_code == 200
    assert response.json()["total_quantity"] == 200


# ─────────────────────────────────────────────────────────────
# Products — role gate, company scoping (via merch_details -> idol), price lock
# ─────────────────────────────────────────────────────────────

def test_update_product_cross_company_manager_forbidden(factory):
    owning_company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    category = factory.category()
    product = factory.product(category.id)
    idol = factory.idol(owning_company.id)
    factory.merch_detail(product.id, idol.id)

    response = client.put(
        f"/products/update/{product.id}", json=product_payload(product, name="Hijacked"),
        headers=factory.token(other_manager),
    )
    assert response.status_code == 403


def test_update_product_price_locked_for_owning_manager(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    category = factory.category()
    product = factory.product(category.id, price=999.0)
    idol = factory.idol(company.id)
    factory.merch_detail(product.id, idol.id)

    response = client.put(
        f"/products/update/{product.id}", json=product_payload(product, price=500.0),
        headers=factory.token(manager),
    )
    assert response.status_code == 403
    assert "price" in response.json()["detail"].lower()


def test_update_product_non_price_field_editable_by_owning_manager(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    category = factory.category()
    product = factory.product(category.id, price=999.0)
    idol = factory.idol(company.id)
    factory.merch_detail(product.id, idol.id)

    response = client.put(
        f"/products/update/{product.id}", json=product_payload(product, name="Renamed Product"),
        headers=factory.token(manager),
    )
    assert response.status_code == 200
    assert response.json()["msg"] == "Product Updated successfully"


def test_update_ownerless_product_price_still_locked_for_any_manager(factory):
    # No merch_details row at all — _manager_scope_violation lets any
    # manager through (§3.17: ownerless merch is manageable by anyone), but
    # the price ban is a flat role check, independent of ownership.
    unrelated_manager = factory.user(role="manager", company_id=factory.company().id)
    category = factory.category()
    product = factory.product(category.id, price=999.0)

    response = client.put(
        f"/products/update/{product.id}", json=product_payload(product, price=1.0),
        headers=factory.token(unrelated_manager),
    )
    assert response.status_code == 403


def test_update_product_price_editable_by_admin(factory):
    category = factory.category()
    product = factory.product(category.id, price=999.0)
    admin = factory.user(role="admin")

    response = client.put(
        f"/products/update/{product.id}", json=product_payload(product, price=500.0),
        headers=factory.token(admin),
    )
    assert response.status_code == 200


# ─────────────────────────────────────────────────────────────
# Direct Sale Campaigns — role gate, company scoping, sale_method validation
# ─────────────────────────────────────────────────────────────

def test_add_direct_sale_campaign_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="direct")
    response = client.post(
        "/direct_sale_campaigns/add", json=direct_sale_campaign_payload(ticket_type.id),
        headers=factory.token(other_manager),
    )
    assert response.status_code == 403


def test_add_direct_sale_campaign_manager_own_company_allowed(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="direct")
    response = client.post(
        "/direct_sale_campaigns/add", json=direct_sale_campaign_payload(ticket_type.id),
        headers=factory.token(manager),
    )
    assert response.status_code == 200
    factory.created.append(factory.db.get(DirectSaleCampaign, uuid.UUID(response.json()["id"])))


def test_add_direct_sale_campaign_rejects_lottery_ticket_type(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="lottery")
    response = client.post(
        "/direct_sale_campaigns/add", json=direct_sale_campaign_payload(ticket_type.id),
        headers=factory.token(manager),
    )
    assert response.status_code == 400


def test_update_direct_sale_campaign_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="direct")
    campaign = factory.direct_sale_campaign(ticket_type.id)
    response = client.put(
        f"/direct_sale_campaigns/update/{campaign.id}",
        json=direct_sale_campaign_payload(ticket_type.id),
        headers=factory.token(other_manager),
    )
    assert response.status_code == 403


def test_delete_direct_sale_campaign_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="direct")
    campaign = factory.direct_sale_campaign(ticket_type.id)
    response = client.delete(
        f"/direct_sale_campaigns/delete/{campaign.id}", headers=factory.token(other_manager),
    )
    assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Lottery Campaigns — role gate, company scoping, sale_method validation
# ─────────────────────────────────────────────────────────────

def test_add_lottery_campaign_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="lottery")
    response = client.post(
        "/lottery_campaigns/add", json=lottery_campaign_payload(ticket_type.id),
        headers=factory.token(other_manager),
    )
    assert response.status_code == 403


def test_add_lottery_campaign_manager_own_company_allowed(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="lottery")
    response = client.post(
        "/lottery_campaigns/add", json=lottery_campaign_payload(ticket_type.id),
        headers=factory.token(manager),
    )
    assert response.status_code == 200
    assert response.json()["draw_at"] is None  # not drawn yet — see docs/project_status.md §8
    factory.created.append(factory.db.get(LotteryCampaign, uuid.UUID(response.json()["id"])))


def test_add_lottery_campaign_rejects_direct_ticket_type(factory):
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="direct")
    response = client.post(
        "/lottery_campaigns/add", json=lottery_campaign_payload(ticket_type.id),
        headers=factory.token(manager),
    )
    assert response.status_code == 400


def test_update_lottery_campaign_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="lottery")
    campaign = factory.lottery_campaign(ticket_type.id)
    response = client.put(
        f"/lottery_campaigns/update/{campaign.id}",
        json=lottery_campaign_payload(ticket_type.id),
        headers=factory.token(other_manager),
    )
    assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Lottery draw (PUT /concerts/lottery-draw/{id}) — role gate + company scoping
# ─────────────────────────────────────────────────────────────

def test_draw_lottery_unauthenticated(factory):
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    response = client.put(f"/concerts/lottery-draw/{concert.id}")
    assert response.status_code == 401


def test_draw_lottery_fan_forbidden(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    response = client.put(f"/concerts/lottery-draw/{concert.id}", headers=factory.token(fan))
    assert response.status_code == 403


def test_draw_lottery_cross_company_manager_forbidden(factory):
    company = factory.company()
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    response = client.put(f"/concerts/lottery-draw/{concert.id}", headers=factory.token(other_manager))
    assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Ticket checkout — on-sale gate (DirectSaleCampaign)
# ─────────────────────────────────────────────────────────────

def _ticket_checkout_payload(ticket_type, **overrides):
    payload = {
        "ticket_type_id": str(ticket_type.id),
        "amount": with_tax(float(ticket_type.price)),
        "gateway": "mock",
        "simulate_succ": True,
        "idempotency_key": str(uuid.uuid4()),
    }
    payload.update(overrides)
    return payload


def test_checkout_ticket_not_on_sale_rejected(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="direct", price=50.0, total_quantity=10)
    # No DirectSaleCampaign at all for this ticket type.
    response = client.post(
        "/tickets/checkout", json=_ticket_checkout_payload(ticket_type), headers=factory.token(fan),
    )
    assert response.status_code == 400
    assert "not currently on sale" in response.json()["detail"].lower()


def test_checkout_ticket_succeeds_when_on_sale(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="direct", price=50.0, total_quantity=10)
    factory.direct_sale_campaign(ticket_type.id)

    response = client.post(
        "/tickets/checkout", json=_ticket_checkout_payload(ticket_type), headers=factory.token(fan),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    factory.created.append(factory.db.get(Ticket, uuid.UUID(response.json()["id"])))


def test_checkout_ticket_rejected_outside_campaign_window(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    ticket_type = factory.ticket_type(concert.id, sale_method="direct", price=50.0, total_quantity=10)
    # Campaign exists but hasn't started yet.
    now = datetime.now(timezone.utc)
    factory.direct_sale_campaign(
        ticket_type.id, sale_start_at=now + timedelta(days=1), sale_end_at=now + timedelta(days=30),
    )

    response = client.post(
        "/tickets/checkout", json=_ticket_checkout_payload(ticket_type), headers=factory.token(fan),
    )
    assert response.status_code == 400
    assert "not currently on sale" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────
# Cross-checks between the direct-sale and lottery paths — a fan shouldn't
# be able to hold a claim on the same concert through both at once.
# ─────────────────────────────────────────────────────────────

def test_apply_to_lottery_rejected_when_fan_already_has_ticket(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    direct_tt = factory.ticket_type(concert.id, tier="regular", sale_method="direct", price=50.0, total_quantity=10)
    factory.direct_sale_campaign(direct_tt.id)
    checkout_resp = client.post(
        "/tickets/checkout", json=_ticket_checkout_payload(direct_tt), headers=factory.token(fan),
    )
    assert checkout_resp.status_code == 200
    factory.created.append(factory.db.get(Ticket, uuid.UUID(checkout_resp.json()["id"])))

    lottery_tt = factory.ticket_type(concert.id, tier="vip", sale_method="lottery", price=100.0, total_quantity=10)
    campaign = factory.lottery_campaign(lottery_tt.id)
    factory.lottery_preference(concert.id, fan.id, lottery_tt.id, rank=1)

    response = client.post(
        "/lottery_entries/apply", json={"campaign_id": str(campaign.id)}, headers=factory.token(fan),
    )
    assert response.status_code == 400
    assert "already hold a ticket" in response.json()["detail"].lower()


def test_checkout_ticket_rejected_with_pending_lottery_entry(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    lottery_tt = factory.ticket_type(concert.id, tier="vip", sale_method="lottery", price=100.0, total_quantity=10)
    campaign = factory.lottery_campaign(lottery_tt.id)
    factory.lottery_preference(concert.id, fan.id, lottery_tt.id, rank=1)
    factory.lottery_entry(campaign.id, fan.id, status="pending")

    direct_tt = factory.ticket_type(concert.id, tier="regular", sale_method="direct", price=50.0, total_quantity=10)
    factory.direct_sale_campaign(direct_tt.id)

    response = client.post(
        "/tickets/checkout", json=_ticket_checkout_payload(direct_tt), headers=factory.token(fan),
    )
    assert response.status_code == 400
    assert "pending or won lottery application" in response.json()["detail"].lower()


def test_checkout_ticket_rejected_with_won_lottery_entry(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    lottery_tt = factory.ticket_type(concert.id, tier="vip", sale_method="lottery", price=100.0, total_quantity=10)
    campaign = factory.lottery_campaign(lottery_tt.id)
    factory.lottery_preference(concert.id, fan.id, lottery_tt.id, rank=1)
    # "won" without a live ticket behind it (e.g. the won ticket already
    # expired unpaid) — _existing_live_ticket alone wouldn't catch this,
    # which is exactly why the lottery-entry check is a separate query.
    factory.lottery_entry(campaign.id, fan.id, status="won")

    direct_tt = factory.ticket_type(concert.id, tier="regular", sale_method="direct", price=50.0, total_quantity=10)
    factory.direct_sale_campaign(direct_tt.id)

    response = client.post(
        "/tickets/checkout", json=_ticket_checkout_payload(direct_tt), headers=factory.token(fan),
    )
    assert response.status_code == 400
    assert "pending or won lottery application" in response.json()["detail"].lower()


def test_checkout_ticket_allowed_with_lost_lottery_entry(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    lottery_tt = factory.ticket_type(concert.id, tier="vip", sale_method="lottery", price=100.0, total_quantity=10)
    campaign = factory.lottery_campaign(lottery_tt.id)
    factory.lottery_preference(concert.id, fan.id, lottery_tt.id, rank=1)
    factory.lottery_entry(campaign.id, fan.id, status="lost")

    direct_tt = factory.ticket_type(concert.id, tier="regular", sale_method="direct", price=50.0, total_quantity=10)
    factory.direct_sale_campaign(direct_tt.id)

    response = client.post(
        "/tickets/checkout", json=_ticket_checkout_payload(direct_tt), headers=factory.token(fan),
    )
    assert response.status_code == 200


# ─────────────────────────────────────────────────────────────
# Lottery Preferences — fan-facing, self-scoped (no cross-company checks;
# any authenticated fan just ranks their own preferences)
# ─────────────────────────────────────────────────────────────

def test_set_preferences_unauthenticated(factory):
    response = client.post("/lottery_preferences/set", json={"concert_id": str(uuid.uuid4()), "ticket_type_ids_in_order": [str(uuid.uuid4())]})
    assert response.status_code == 401


def test_set_preferences_concert_not_found(factory):
    fan = factory.user(role="fan")
    response = client.post(
        "/lottery_preferences/set",
        json={"concert_id": str(uuid.uuid4()), "ticket_type_ids_in_order": [str(uuid.uuid4())]},
        headers=factory.token(fan),
    )
    assert response.status_code == 404


def test_set_preferences_duplicate_ticket_type_rejected(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="lottery")

    response = client.post(
        "/lottery_preferences/set",
        json={"concert_id": str(concert.id), "ticket_type_ids_in_order": [str(tt.id), str(tt.id)]},
        headers=factory.token(fan),
    )
    assert response.status_code == 400


def test_set_preferences_direct_sale_ticket_type_rejected(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="direct")

    response = client.post(
        "/lottery_preferences/set",
        json={"concert_id": str(concert.id), "ticket_type_ids_in_order": [str(tt.id)]},
        headers=factory.token(fan),
    )
    assert response.status_code == 400


def test_set_preferences_success_then_list_then_clear(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    vip = factory.ticket_type(concert.id, tier="vip", sale_method="lottery")
    premium = factory.ticket_type(concert.id, tier="premium", sale_method="lottery")
    factory.lottery_campaign(vip.id)
    factory.lottery_campaign(premium.id)

    set_response = client.post(
        "/lottery_preferences/set",
        json={"concert_id": str(concert.id), "ticket_type_ids_in_order": [str(vip.id), str(premium.id)]},
        headers=factory.token(fan),
    )
    assert set_response.status_code == 200
    ranked = set_response.json()
    assert [row["ticket_type_id"] for row in ranked] == [str(vip.id), str(premium.id)]
    assert [row["rank"] for row in ranked] == [1, 2]
    for row in ranked:
        factory.created.append(factory.db.get(LotteryPreference, uuid.UUID(row["id"])))

    list_response = client.get(f"/lottery_preferences/mine/{concert.id}", headers=factory.token(fan))
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2

    delete_response = client.delete(f"/lottery_preferences/mine/{concert.id}", headers=factory.token(fan))
    assert delete_response.status_code == 200
    factory.created = [obj for obj in factory.created if not isinstance(obj, LotteryPreference)]  # already deleted by the request above

    assert client.get(f"/lottery_preferences/mine/{concert.id}", headers=factory.token(fan)).status_code == 404


def test_set_preferences_tier_without_campaign_not_found(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="lottery")

    response = client.post(
        "/lottery_preferences/set",
        json={"concert_id": str(concert.id), "ticket_type_ids_in_order": [str(tt.id)]},
        headers=factory.token(fan),
    )
    assert response.status_code == 404


def test_list_my_preferences_none_set(factory):
    fan = factory.user(role="fan")
    response = client.get(f"/lottery_preferences/mine/{uuid.uuid4()}", headers=factory.token(fan))
    assert response.status_code == 404


def test_clear_my_preferences_none_set(factory):
    fan = factory.user(role="fan")
    response = client.delete(f"/lottery_preferences/mine/{uuid.uuid4()}", headers=factory.token(fan))
    assert response.status_code == 404


# ─────────────────────────────────────────────────────────────
# Lottery Entries — beyond /apply (already covered above via the
# direct/lottery cross-checks)
# ─────────────────────────────────────────────────────────────

def test_list_my_entries_none(factory):
    fan = factory.user(role="fan")
    response = client.get("/lottery_entries/mine", headers=factory.token(fan))
    assert response.status_code == 404


def test_list_my_entries_found(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="lottery")
    campaign = factory.lottery_campaign(tt.id)
    factory.lottery_preference(concert.id, fan.id, tt.id, rank=1)

    apply_response = client.post("/lottery_entries/apply", json={"campaign_id": str(campaign.id)}, headers=factory.token(fan))
    assert apply_response.status_code == 200
    factory.created.append(factory.db.get(LotteryEntry, uuid.UUID(apply_response.json()["id"])))

    response = client.get("/lottery_entries/mine", headers=factory.token(fan))
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_campaign_entries_unauthenticated(factory):
    response = client.get(f"/lottery_entries/campaign/{uuid.uuid4()}")
    assert response.status_code == 401


def test_list_campaign_entries_fan_forbidden(factory):
    fan = factory.user(role="fan")
    response = client.get(f"/lottery_entries/campaign/{uuid.uuid4()}", headers=factory.token(fan))
    assert response.status_code == 403


def test_list_campaign_entries_manager_wrong_company_forbidden(factory):
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="lottery")
    campaign = factory.lottery_campaign(tt.id)

    response = client.get(f"/lottery_entries/campaign/{campaign.id}", headers=factory.token(other_manager))
    assert response.status_code == 403


def test_list_campaign_entries_success_for_owning_manager(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="lottery")
    campaign = factory.lottery_campaign(tt.id)
    factory.lottery_preference(concert.id, fan.id, tt.id, rank=1)

    apply_response = client.post("/lottery_entries/apply", json={"campaign_id": str(campaign.id)}, headers=factory.token(fan))
    factory.created.append(factory.db.get(LotteryEntry, uuid.UUID(apply_response.json()["id"])))

    response = client.get(f"/lottery_entries/campaign/{campaign.id}", headers=factory.token(manager))
    assert response.status_code == 200
    assert len(response.json()) == 1


# ─────────────────────────────────────────────────────────────
# Tickets — beyond /checkout (already covered above)
# ─────────────────────────────────────────────────────────────

def test_add_ticket_requires_admin(factory):
    manager = factory.user(role="manager", company_id=factory.company().id)
    response = client.post(
        "/tickets/add", json={"ticket_type_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4())}, headers=factory.token(manager),
    )
    assert response.status_code == 403


def test_add_ticket_admin_can_issue_directly(factory):
    admin = factory.user(role="admin")
    target_fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="lottery")

    response = client.post(
        "/tickets/add", json={"ticket_type_id": str(tt.id), "user_id": str(target_fan.id)}, headers=factory.token(admin),
    )
    assert response.status_code == 200
    factory.created.append(factory.db.get(Ticket, uuid.UUID(response.json()["id"])))


def test_get_ticket_by_id_not_found(factory):
    fan = factory.user(role="fan")
    response = client.get(f"/tickets/{uuid.uuid4()}", headers=factory.token(fan))
    assert response.status_code == 404


def test_get_ticket_by_id_other_fan_forbidden(factory):
    owner = factory.user(role="fan")
    other_fan = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="direct")
    factory.direct_sale_campaign(tt.id)
    checkout_response = client.post("/tickets/checkout", json=_ticket_checkout_payload(tt), headers=factory.token(owner))
    ticket_id = checkout_response.json()["id"]
    factory.created.append(factory.db.get(Ticket, uuid.UUID(ticket_id)))

    response = client.get(f"/tickets/{ticket_id}", headers=factory.token(other_fan))
    assert response.status_code == 403


def test_get_ticket_by_id_owner_and_admin_both_allowed(factory):
    owner = factory.user(role="fan")
    admin = factory.user(role="admin")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="direct")
    factory.direct_sale_campaign(tt.id)
    checkout_response = client.post("/tickets/checkout", json=_ticket_checkout_payload(tt), headers=factory.token(owner))
    ticket_id = checkout_response.json()["id"]
    factory.created.append(factory.db.get(Ticket, uuid.UUID(ticket_id)))

    assert client.get(f"/tickets/{ticket_id}", headers=factory.token(owner)).status_code == 200
    assert client.get(f"/tickets/{ticket_id}", headers=factory.token(admin)).status_code == 200


def test_get_concert_sales_unauthenticated(factory):
    response = client.get(f"/tickets/concert/{uuid.uuid4()}/sales")
    assert response.status_code == 401


def test_get_concert_sales_cross_company_manager_forbidden(factory):
    other_manager = factory.user(role="manager", company_id=factory.company().id)
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)

    response = client.get(f"/tickets/concert/{concert.id}/sales", headers=factory.token(other_manager))
    assert response.status_code == 403


def test_get_concert_sales_owning_manager_success(factory):
    fan = factory.user(role="fan")
    company = factory.company()
    manager = factory.user(role="manager", company_id=company.id)
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="direct")
    factory.direct_sale_campaign(tt.id)
    checkout_response = client.post("/tickets/checkout", json=_ticket_checkout_payload(tt), headers=factory.token(fan))
    factory.created.append(factory.db.get(Ticket, uuid.UUID(checkout_response.json()["id"])))

    response = client.get(f"/tickets/concert/{concert.id}/sales", headers=factory.token(manager))
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["data"][0]["source"] == "direct"


def test_update_ticket_requires_admin(factory):
    manager = factory.user(role="manager", company_id=factory.company().id)
    response = client.put(f"/tickets/update/{uuid.uuid4()}", json={"status": "used"}, headers=factory.token(manager))
    assert response.status_code == 403


def test_update_ticket_admin_success(factory):
    admin = factory.user(role="admin")
    owner = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="direct")
    factory.direct_sale_campaign(tt.id)
    checkout_response = client.post("/tickets/checkout", json=_ticket_checkout_payload(tt), headers=factory.token(owner))
    ticket_id = checkout_response.json()["id"]
    factory.created.append(factory.db.get(Ticket, uuid.UUID(ticket_id)))

    response = client.put(f"/tickets/update/{ticket_id}", json={"status": "used"}, headers=factory.token(admin))
    assert response.status_code == 200
    assert response.json()["status"] == "used"


def test_delete_ticket_requires_admin(factory):
    manager = factory.user(role="manager", company_id=factory.company().id)
    response = client.delete(f"/tickets/delete/{uuid.uuid4()}", headers=factory.token(manager))
    assert response.status_code == 403


def test_delete_ticket_admin_success(factory):
    admin = factory.user(role="admin")
    owner = factory.user(role="fan")
    company = factory.company()
    venue = factory.venue()
    concert = factory.concert(company.id, venue.id)
    tt = factory.ticket_type(concert.id, sale_method="direct")
    factory.direct_sale_campaign(tt.id)
    checkout_response = client.post("/tickets/checkout", json=_ticket_checkout_payload(tt), headers=factory.token(owner))
    ticket_id = checkout_response.json()["id"]

    response = client.delete(f"/tickets/delete/{ticket_id}", headers=factory.token(admin))
    assert response.status_code == 200
    # Already deleted by the request above — nothing left for the fixture's
    # own teardown to clean up.
