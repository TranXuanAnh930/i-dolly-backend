import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.marketplace import ShippingAddress
from main import app

# ───────────────────────────────────────────────────────────────
# Shipping addresses over real HTTP + Postgres, focused on ownership: every read and write by id
# must be limited to the caller's own addresses. These run against the real query rather than a
# mocked Session because a mocked filter() accepts any condition, including one that never
# references ShippingAddress.user_id at all.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)

ADDRESS = {
    "address_line1": "2-1 Marunouchi", "address_line2": "Apt 5", "city": "Tokyo",
    "postal_code": "100-0005", "state": "Tokyo", "country": "Japan",
}


@pytest.fixture
def people(seed):
    owner, other = seed.user("fan"), seed.user("fan")
    return seed, owner, other, seed.address(owner.id)


def address_row(seed, address_id):
    seed.db.expire_all()
    return seed.db.get(ShippingAddress, address_id)


def test_add_then_list_own_addresses(people):
    seed, owner, other, existing = people

    res = client.post("/shipping_addresses/add", json=ADDRESS, headers=seed.headers(owner))
    assert res.status_code == 200
    assert res.json()["user_id"] == str(owner.id)

    listed = client.get("/shipping_addresses/fetch", headers=seed.headers(owner)).json()
    assert {a["id"] for a in listed} == {str(existing.id), res.json()["id"]}


def test_list_with_no_addresses_is_empty(people):
    seed, _, other, _ = people
    res = client.get("/shipping_addresses/fetch", headers=seed.headers(other))
    assert (res.status_code, res.json()) == (200, [])


def test_fetch_by_id_own_address(people):
    seed, owner, _, address = people
    res = client.get(f"/shipping_addresses/fetch_byid/{address.id}", headers=seed.headers(owner))
    assert res.status_code == 200
    assert res.json()["id"] == str(address.id)


def test_fetch_by_id_other_users_address_404(people):
    seed, _, other, address = people
    assert client.get(f"/shipping_addresses/fetch_byid/{address.id}", headers=seed.headers(other)).status_code == 404


def test_fetch_by_id_requires_auth(people):
    _, _, _, address = people
    assert client.get(f"/shipping_addresses/fetch_byid/{address.id}").status_code == 401


def test_update_own_address(people):
    seed, owner, _, address = people
    res = client.put(f"/shipping_addresses/update/{address.id}", json=ADDRESS, headers=seed.headers(owner))

    assert res.status_code == 200
    assert address_row(seed, address.id).address_line1 == ADDRESS["address_line1"]


def test_cannot_update_other_users_address(people):
    seed, _, other, address = people
    before = address.address_line1

    res = client.put(f"/shipping_addresses/update/{address.id}", json=ADDRESS, headers=seed.headers(other))
    assert res.status_code == 404
    assert address_row(seed, address.id).address_line1 == before


def test_update_missing_address_404(people):
    seed, owner, _, _ = people
    res = client.put(f"/shipping_addresses/update/{uuid.uuid4()}", json=ADDRESS, headers=seed.headers(owner))
    assert res.status_code == 404


def test_cannot_delete_other_users_address(people):
    seed, _, other, address = people

    assert client.delete(f"/shipping_addresses/delete/{address.id}", headers=seed.headers(other)).status_code == 404
    assert address_row(seed, address.id) is not None


def test_delete_own_address(people):
    seed, owner, _, address = people
    address_id = address.id

    assert client.delete(f"/shipping_addresses/delete/{address_id}", headers=seed.headers(owner)).status_code == 200
    assert address_row(seed, address_id) is None
    assert client.delete(f"/shipping_addresses/delete/{address_id}", headers=seed.headers(owner)).status_code == 404
