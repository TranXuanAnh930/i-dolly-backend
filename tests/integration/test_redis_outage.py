import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import redis
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError

from app.db.models.events import DirectSaleCampaign, Ticket
from app.db.models.marketplace import Order, Product
from app.utils.tax import with_tax
from main import app
from tests.conftest import fake_redis

# ───────────────────────────────────────────────────────────────
# Redis outage (bugs.md #11) over real HTTP + Postgres. With Redis down, pages are answered from
# Postgres and a write that committed reports success. Tests marked "Guard" pass already.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)


@pytest.fixture
def redis_down(monkeypatch):
    """Redis (cache, rate limiter) unreachable for the rest of the test."""
    def unreachable(*args, **kwargs):
        raise redis.ConnectionError("Error connecting to redis:6379")

    for command in ("get", "setex", "set", "delete", "keys", "incr", "ttl", "pipeline"):
        monkeypatch.setattr(fake_redis, command, unreachable)


@pytest.fixture
def broker_down():
    """The Celery broker (also Redis) unreachable: every send_task raises."""
    with patch("app.celery_app.celery_app.send_task", side_effect=OperationalError("Error 111 connecting to redis:6379")) as send:
        yield send


@pytest.fixture
def world(seed):
    company, venue = seed.company(), seed.venue()
    concert = seed.concert(company.id, venue.id)
    direct = seed.ticket_type(concert.id, sale_method="direct")
    now = datetime.now(timezone.utc)
    seed.save(DirectSaleCampaign(ticket_type_id=direct.id, sale_start_at=now - timedelta(days=1), sale_end_at=now + timedelta(days=30)))
    category = seed.category()
    product = seed.product(category.id, price=1000.0, quantity=10)
    return {
        "seed": seed, "concert": concert, "direct": direct, "category": category, "product": product,
        "manager": seed.user("manager", company.id), "admin": seed.user("admin"), "fan": seed.user("fan"),
    }


def checkout_order(world):
    seed, fan = world["seed"], world["fan"]
    headers = seed.headers(fan)
    assert client.post("/cart/add_cart", json={"product_id": str(world["product"].id), "quantity": 1}, headers=headers).status_code == 200
    return client.post("/order/checkout", headers=headers, json={
        "amount": with_tax(world["product"].price), "shipping_address_id": str(seed.address(fan.id).id),
        "gateway": "mock", "simulate_succ": True, "idempotency_key": str(uuid.uuid4()),
    })


# ─── reads ─────────────────────────────────────────────────────

def test_store_page_is_served_from_postgres_when_redis_is_down(world, redis_down):
    res = client.get("/products/store-page")

    assert res.status_code == 200
    assert str(world["product"].id) in {p["id"] for p in res.json()["products"]}


def test_concert_detail_is_served_when_redis_is_down(world, redis_down):
    res = client.get(f"/concerts/{world['concert'].id}/detail")

    assert res.status_code == 200


# ─── writes that committed report success ──────────────────────

def test_order_checkout_succeeds_when_redis_and_the_broker_are_down(world, redis_down, broker_down):
    seed = world["seed"]
    res = checkout_order(world)

    assert res.status_code == 200, res.json()
    assert res.json()["status"] == "confirmed"
    seed.track(Order, uuid.UUID(res.json()["id"]))
    seed.db.expire_all()
    assert seed.db.get(Product, world["product"].id).quantity == 9


def test_ticket_checkout_succeeds_when_redis_and_the_broker_are_down(world, redis_down, broker_down):
    seed = world["seed"]
    res = client.post("/tickets/checkout", headers=seed.headers(world["fan"]), json={
        "ticket_type_id": str(world["direct"].id), "amount": with_tax(float(world["direct"].price)),
        "gateway": "mock", "simulate_succ": True, "idempotency_key": str(uuid.uuid4()),
    })

    assert res.status_code == 200, res.json()
    assert res.json()["status"] == "paid"
    seed.db.expire_all()
    assert seed.db.get(Ticket, uuid.UUID(res.json()["id"])).status.value == "paid"


def test_manager_product_update_succeeds_when_redis_is_down(world, redis_down):
    seed, product = world["seed"], world["product"]
    payload = {"name": "renamed", "price": product.price, "description": "d", "quantity": 7,
               "category_id": str(world["category"].id)}

    res = client.put(f"/products/update/{product.id}", json=payload, headers=seed.headers(world["admin"]))

    assert res.status_code == 200
    seed.db.expire_all()
    assert seed.db.get(Product, product.id).name == "renamed"


def test_checkout_works_normally_when_everything_is_up(world):
    # Guard
    with patch("app.celery_app.celery_app.send_task") as send:
        res = checkout_order(world)
    assert res.status_code == 200
    world["seed"].track(Order, uuid.UUID(res.json()["id"]))
    send.assert_called_once()


# ─── the lottery draw: queueing it is the operation ────────────

def test_lottery_draw_answers_503_when_the_broker_is_down(world, broker_down):
    seed = world["seed"]
    res = client.put(f"/concerts/lottery-draw/{world['concert'].id}", headers=seed.headers(world["manager"]))

    assert res.status_code == 503
    assert res.json()["code"] == "service_unavailable"


def test_lottery_draw_is_scheduled_when_the_broker_is_up(world):
    # Guard
    seed = world["seed"]
    with patch("app.celery_app.celery_app.send_task") as send:
        res = client.put(f"/concerts/lottery-draw/{world['concert'].id}", headers=seed.headers(world["manager"]))
    assert res.status_code == 200
    send.assert_called_once()
