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

from tests.conftest import fake_redis
from main import app
from app.db.session import session as db_session
from app.db.models.management_company import ManagementCompany
from app.db.models.user import Users
from app.db.models.venue import Venue
from app.db.models.concert import Concert
from app.db.models.ticket_type import TicketType
from app.db.models.category import Category
from app.db.models.products import Product
from app.db.models.idol import Idol
from app.db.models.merch_detail import MerchDetail
from app.utils.hashing import hash_password
from app.utils.jwt_manager import create_access_token

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    for key in fake_redis.scan_iter("rate:ip:*"):
        fake_redis.delete(key)
    for key in fake_redis.scan_iter("rate:user:*"):
        fake_redis.delete(key)
    yield


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
