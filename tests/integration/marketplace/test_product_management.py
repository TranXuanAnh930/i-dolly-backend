import io
import uuid
from unittest.mock import patch

import pytest
import sqlalchemy
from fastapi.testclient import TestClient

from app.db.models.marketplace import AlbumDetail, Cart, MerchDetail, OrderItem, Product
from app.utils.tax import with_tax
from main import app

# ───────────────────────────────────────────────────────────────
# Product management over real HTTP + Postgres: creating a product together with its
# album/merch detail (company-scoped through the idol/group it's attached to), image upload,
# soft delete and reactivation, bulk add, the company-scoped manager pages, sales history, and the
# public read pages.
# Price-lock rules on update are covered in tests/integration/test_permissions.py.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)
PNG = ("cover.png", io.BytesIO(b"\x89PNG fake"), "image/png")


@pytest.fixture(autouse=True)
def local_storage(tmp_path):
    """Uploads land in a temp dir instead of the repo's uploads/ folder."""
    from app.utils import storage

    with patch.object(storage.settings, "LOCAL_UPLOAD_DIR", str(tmp_path)):
        with patch.object(storage, "_backend", storage.LocalStorageBackend()):
            yield tmp_path


@pytest.fixture
def world(seed):
    company_a, company_b = seed.company(), seed.company()
    return {
        "seed": seed,
        "company_a": company_a, "company_b": company_b,
        "category": seed.category(),
        "idol_a": seed.idol(company_a.id),
        "group_b": seed.group(company_b.id),
        "manager_a": seed.user("manager", company_a.id),
        "manager_b": seed.user("manager", company_b.id),
        "admin": seed.user("admin"),
        "fan": seed.user("fan"),
    }


def detail_form(category_id, **overrides):
    form = {
        "name": f"product-{uuid.uuid4()}", "price": "1500", "description": "Limited edition",
        "quantity": "20", "category_id": str(category_id), "detail_kind": "album",
    }
    form.update({k: str(v) for k, v in overrides.items() if v is not None})
    return form


def add_with_detail(world, user, files=None, **overrides):
    return client.post(
        "/products/add_with_detail", data=detail_form(world["category"].id, **overrides),
        files=files, headers=world["seed"].headers(user),
    )


def created_product(world, name) -> Product:
    seed = world["seed"]
    product = seed.db.query(Product).filter(Product.name == name).one()
    seed.track(Product, product.id)
    return product


# ───────────────────────────────────────────────────────────────
# POST /products/add_with_detail
# ───────────────────────────────────────────────────────────────

def test_manager_adds_album_for_own_idol_with_image(world, local_storage):
    name = f"album-{uuid.uuid4()}"
    res = add_with_detail(world, world["manager_a"], files={"image": PNG}, name=name,
                          idol_id=world["idol_a"].id, release_date="2025-01-15", track_count=8)

    assert res.status_code == 200, res.text
    product = created_product(world, name)
    album = world["seed"].db.get(AlbumDetail, product.id)
    assert album.idol_id == world["idol_a"].id and album.track_count == 8
    assert product.image_url.startswith("/uploads/products/")
    assert len(list((local_storage / "products").iterdir())) == 1


def test_manager_adds_merch_for_group_with_color(world):
    seed = world["seed"]
    color = seed.color()
    name = f"merch-{uuid.uuid4()}"
    res = add_with_detail(world, world["manager_b"], name=name, detail_kind="merch",
                          group_id=world["group_b"].id, edition="Ver. 2", color_id=color.id)

    assert res.status_code == 200, res.text
    merch = seed.db.get(MerchDetail, created_product(world, name).id)
    assert (merch.group_id, merch.edition, merch.color_id) == (world["group_b"].id, "Ver. 2", color.id)


def test_manager_cannot_add_for_other_companys_idol(world):
    name = f"album-{uuid.uuid4()}"
    res = add_with_detail(world, world["manager_b"], name=name, idol_id=world["idol_a"].id)

    assert res.status_code == 403
    assert world["seed"].db.query(Product).filter(Product.name == name).count() == 0


def test_admin_adds_for_any_company(world):
    name = f"album-{uuid.uuid4()}"
    res = add_with_detail(world, world["admin"], name=name, group_id=world["group_b"].id)
    assert res.status_code == 200
    created_product(world, name)


def test_deactivated_owner_rejected(world):
    idol = world["seed"].idol(world["company_a"].id, is_active=False)
    res = add_with_detail(world, world["admin"], idol_id=idol.id)
    assert res.status_code == 400


@pytest.mark.parametrize("missing", ["category_id", "idol_id", "group_id", "color_id"])
def test_missing_reference_404(world, missing):
    overrides = {"idol_id": world["idol_a"].id, "detail_kind": "merch"}
    if missing == "group_id":
        overrides = {"group_id": uuid.uuid4(), "detail_kind": "merch"}
    elif missing == "idol_id":
        overrides["idol_id"] = uuid.uuid4()
    elif missing == "color_id":
        overrides["color_id"] = uuid.uuid4()
    form = detail_form(world["category"].id, **overrides)
    if missing == "category_id":
        form["category_id"] = str(uuid.uuid4())

    res = client.post("/products/add_with_detail", data=form, headers=world["seed"].headers(world["admin"]))
    assert res.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"detail_kind": "poster"},
        {"detail_kind": "album"},  # album needs an idol or group
        {"detail_kind": "merch", "both": True},  # merch needs exactly one
    ],
)
def test_invalid_detail_combination_422(world, overrides):
    extra = {"idol_id": world["idol_a"].id, "group_id": world["group_b"].id} if overrides.pop("both", False) else {}
    res = add_with_detail(world, world["admin"], **overrides, **extra)
    assert res.status_code == 422


def test_non_image_upload_rejected(world):
    res = add_with_detail(world, world["admin"], files={"image": ("x.html", io.BytesIO(b"<p>"), "text/html")},
                          idol_id=world["idol_a"].id)
    assert res.status_code == 400


def test_fan_cannot_add_products(world):
    assert add_with_detail(world, world["fan"], idol_id=world["idol_a"].id).status_code == 403


# ───────────────────────────────────────────────────────────────
# POST /products/add_product, /bulk_products
# ───────────────────────────────────────────────────────────────

def test_add_plain_product_with_image(world):
    name = f"plain-{uuid.uuid4()}"
    form = {"name": name, "price": "500", "description": "d", "quantity": "3", "category_id": str(world["category"].id)}
    res = client.post("/products/add_product", data=form, files={"image": PNG}, headers=world["seed"].headers(world["admin"]))

    assert res.status_code == 200
    assert created_product(world, name).image_url.endswith(".png")


def test_add_plain_product_unknown_category_404(world):
    form = {"name": "x", "price": "500", "description": "d", "quantity": "3", "category_id": str(uuid.uuid4())}
    assert client.post("/products/add_product", data=form, headers=world["seed"].headers(world["admin"])).status_code == 404


def test_add_plain_product_bad_image_400(world):
    form = {"name": "x", "price": "500", "description": "d", "quantity": "3", "category_id": str(world["category"].id)}
    files = {"image": ("x.txt", io.BytesIO(b"text"), "text/plain")}
    assert client.post("/products/add_product", data=form, files=files, headers=world["seed"].headers(world["admin"])).status_code == 400


def bulk_item(category_id, name):
    return {"name": name, "price": 100, "description": "d", "quantity": 1, "category_id": str(category_id)}


def test_bulk_add(world):
    names = [f"bulk-{uuid.uuid4()}" for _ in range(3)]
    res = client.post("/products/bulk_products", json=[bulk_item(world["category"].id, n) for n in names],
                      headers=world["seed"].headers(world["admin"]))

    assert res.status_code == 200
    assert res.json()["msg"].startswith("3 ")
    for name in names:
        created_product(world, name)


def test_bulk_add_is_all_or_nothing_on_bad_category(world):
    names = [f"bulk-{uuid.uuid4()}" for _ in range(2)]
    payload = [bulk_item(world["category"].id, names[0]), bulk_item(uuid.uuid4(), names[1])]
    res = client.post("/products/bulk_products", json=payload, headers=world["seed"].headers(world["admin"]))

    assert res.status_code == 404
    assert world["seed"].db.query(Product).filter(Product.name.in_(names)).count() == 0


def test_bulk_add_empty_list_400(world):
    assert client.post("/products/bulk_products", json=[], headers=world["seed"].headers(world["admin"])).status_code == 400


# ───────────────────────────────────────────────────────────────
# Image replace, update, delete (company scoping)
# ───────────────────────────────────────────────────────────────

@pytest.fixture
def owned_products(world):
    """product_a owned by company A (idol merch), product_b by company B (group album), and one ownerless."""
    seed = world["seed"]
    product_a = seed.product(world["category"].id)
    seed.merch(product_a.id, idol_id=world["idol_a"].id)
    product_b = seed.product(world["category"].id)
    seed.album(product_b.id, group_id=world["group_b"].id)
    ownerless = seed.product(world["category"].id)
    return product_a, product_b, ownerless


def test_owning_manager_replaces_image(world, owned_products):
    product_a, _, _ = owned_products
    seed = world["seed"]
    res = client.post(f"/products/{product_a.id}/image", files={"image": PNG}, headers=seed.headers(world["manager_a"]))

    assert res.status_code == 200
    seed.db.refresh(product_a)
    assert product_a.image_url.startswith("/uploads/products/")


def test_other_company_manager_cannot_replace_image(world, owned_products):
    product_a, _, _ = owned_products
    res = client.post(f"/products/{product_a.id}/image", files={"image": PNG}, headers=world["seed"].headers(world["manager_b"]))
    assert res.status_code == 403


def test_replace_image_missing_product_404_and_bad_type_400(world):
    headers = world["seed"].headers(world["admin"])
    assert client.post(f"/products/{uuid.uuid4()}/image", files={"image": PNG}, headers=headers).status_code == 404
    bad = {"image": ("x.svg", io.BytesIO(b"<svg/>"), "image/svg+xml")}
    assert client.post(f"/products/{uuid.uuid4()}/image", files=bad, headers=headers).status_code == 400


def test_update_missing_product_404_and_unknown_category_404(world, owned_products):
    _, _, ownerless = owned_products
    headers = world["seed"].headers(world["admin"])
    payload = {"name": "n", "price": ownerless.price, "description": "d", "quantity": 1, "category_id": str(world["category"].id)}

    assert client.put(f"/products/update/{uuid.uuid4()}", json=payload, headers=headers).status_code == 404
    payload["category_id"] = str(uuid.uuid4())
    assert client.put(f"/products/update/{ownerless.id}", json=payload, headers=headers).status_code == 404


def test_update_replaces_image_url_when_given(world, owned_products):
    _, _, ownerless = owned_products
    seed = world["seed"]
    payload = {"name": "renamed", "price": ownerless.price, "description": "d", "quantity": 4,
               "category_id": str(world["category"].id), "image_url": "/uploads/products/new.png"}

    assert client.put(f"/products/update/{ownerless.id}", json=payload, headers=seed.headers(world["admin"])).status_code == 200
    seed.db.refresh(ownerless)
    assert (ownerless.name, ownerless.quantity, ownerless.image_url) == ("renamed", 4, "/uploads/products/new.png")


def test_delete_scoping(world, owned_products):
    a_id, b_id, ownerless_id = (p.id for p in owned_products)
    seed = world["seed"]
    manager_a = seed.headers(world["manager_a"])

    assert client.delete(f"/products/delete/{b_id}", headers=manager_a).status_code == 403
    assert client.delete(f"/products/delete/{a_id}", headers=manager_a).status_code == 200
    assert client.delete(f"/products/delete/{ownerless_id}", headers=manager_a).status_code == 200
    assert client.delete(f"/products/delete/{uuid.uuid4()}", headers=manager_a).status_code == 404
    seed.db.expire_all()
    assert seed.db.get(Product, b_id).is_active is True
    # Soft delete: the rows are still there, deactivated.
    assert seed.db.get(Product, a_id).is_active is False
    assert seed.db.get(Product, ownerless_id).is_active is False


# ───────────────────────────────────────────────────────────────
# Manager pages + sales history
# ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/products/manager-products-page", "/products/manager-product-form-page"])
def test_manager_product_pages_scoped_by_company(world, owned_products, path):
    product_a, product_b, ownerless = owned_products
    ids = {str(p.id) for p in owned_products}

    def page_ids(user, company_id=None):
        params = {"company_id": str(company_id)} if company_id else {}
        res = client.get(path, params=params, headers=world["seed"].headers(world[user]))
        assert res.status_code == 200
        return {p["id"] for p in res.json()["products"]} & ids

    # Admins choose the company, or omit it for every product.
    assert page_ids("admin", world["company_a"].id) == {str(product_a.id), str(ownerless.id)}
    assert page_ids("admin", world["company_b"].id) == {str(product_b.id), str(ownerless.id)}
    assert page_ids("admin") == ids
    # Managers always get their own company, whatever company_id they send.
    assert page_ids("manager_a") == {str(product_a.id), str(ownerless.id)}
    assert page_ids("manager_a", world["company_b"].id) == {str(product_a.id), str(ownerless.id)}


def test_manager_product_form_page_includes_reference_data(world, owned_products):
    product_a, _, ownerless = owned_products
    res = client.get("/products/manager-product-form-page", headers=world["seed"].headers(world["manager_a"]))

    assert res.status_code == 200
    body = res.json()
    product_ids = {p["id"] for p in body["products"]}
    assert {str(product_a.id), str(ownerless.id)} <= product_ids
    assert str(owned_products[1].id) not in product_ids
    assert str(world["category"].id) in {c["id"] for c in body["categories"]}
    # The idol/group pickers only offer the manager's own company.
    assert {i["company_id"] for i in body["idols"]} == {str(world["company_a"].id)}
    assert str(world["idol_a"].id) in {i["id"] for i in body["idols"]}
    assert str(world["group_b"].id) not in {g["id"] for g in body["groups"]}


def test_admin_product_form_page_offers_every_company(world):
    body = client.get("/products/manager-product-form-page", headers=world["seed"].headers(world["admin"])).json()

    assert str(world["idol_a"].id) in {i["id"] for i in body["idols"]}
    assert str(world["group_b"].id) in {g["id"] for g in body["groups"]}


def test_sales_history(world, owned_products):
    product_a, _, _ = owned_products
    seed = world["seed"]
    order = seed.order(world["fan"].id, [(product_a, 3)])

    res = client.get(f"/products/{product_a.id}/sales", headers=seed.headers(world["manager_a"]))
    assert res.status_code == 200
    [sale] = res.json()["data"]
    assert sale["order_id"] == str(order.id)
    assert sale["quantity"] == 3
    assert sale["line_total"] == product_a.price * 3

    assert client.get(f"/products/{product_a.id}/sales", headers=seed.headers(world["manager_b"])).status_code == 403
    assert client.get(f"/products/{uuid.uuid4()}/sales", headers=seed.headers(world["admin"])).status_code == 404


# ───────────────────────────────────────────────────────────────
# Public reads
# ───────────────────────────────────────────────────────────────

def test_product_detail_resolves_artist_and_recommends_same_artist(world, owned_products):
    product_a, product_b, _ = owned_products
    seed = world["seed"]
    sibling = seed.product(world["category"].id)
    seed.album(sibling.id, idol_id=world["idol_a"].id)

    res = client.get(f"/products/{product_a.id}/detail")
    assert res.status_code == 200
    body = res.json()
    assert body["product"]["artist"] == {
        "type": "idol", "id": str(world["idol_a"].id), "name": world["idol_a"].name, "color_hex": None,
    }
    recommended = {r["id"] for r in body["recommendations"]}
    assert str(sibling.id) in recommended
    assert str(product_b.id) not in recommended


def test_product_detail_falls_back_to_name_match(world):
    seed = world["seed"]
    product = seed.product(world["category"].id, name=f"{world['group_b'].name} Tour Towel")

    artist = client.get(f"/products/{product.id}/detail").json()["product"]["artist"]
    assert (artist["type"], artist["id"]) == ("group", str(world["group_b"].id))


def test_product_detail_missing_404():
    assert client.get(f"/products/{uuid.uuid4()}/detail").status_code == 404


def test_store_page_lists_seeded_products(world, owned_products):
    res = client.get("/products/store-page")
    assert res.status_code == 200
    ids = {p["id"] for p in res.json()["products"]}
    assert {str(p.id) for p in owned_products} <= ids


def test_search_all_pagination_and_filter(world, owned_products):
    product_a, _, _ = owned_products

    found = client.get(f"/products/search/{product_a.id}")
    assert found.status_code == 200
    assert found.json()["category"]["id"] == str(world["category"].id)
    assert client.get(f"/products/search/{uuid.uuid4()}").status_code == 404

    assert str(product_a.id) in {p["id"] for p in client.get("/products/all").json()}
    assert client.get("/products/pagination", params={"page": 1, "limit": 2}).json()["count"] <= 2

    filtered = client.get("/products/filter", params={
        "category": world["category"].name, "name": product_a.name[:12],
        "min_price": int(product_a.price) - 1, "max_price": int(product_a.price) + 1, "limit": 50,
    })
    assert filtered.status_code == 200
    assert str(product_a.id) in {p["id"] for p in filtered.json()["data"]}


# ───────────────────────────────────────────────────────────────
# Soft delete (bugs.md #2): "delete" deactivates, order history survives
# ───────────────────────────────────────────────────────────────

def delete_product(world, product, user_key="admin"):
    res = client.delete(f"/products/delete/{product.id}", headers=world["seed"].headers(world[user_key]))
    assert res.status_code == 200
    world["seed"].db.expire_all()


def test_deleted_product_keeps_its_order_lines(world, owned_products):
    product_a, _, _ = owned_products
    seed = world["seed"]
    order = seed.order(world["fan"].id, [(product_a, 2)])

    delete_product(world, product_a, "manager_a")

    assert seed.db.query(OrderItem).filter(OrderItem.order_id == order.id).count() == 1
    [placed] = client.get("/order/fetch_placed_order", headers=seed.headers(world["fan"])).json()
    assert [(i["product_id"], i["quantity"]) for i in placed["items"]] == [(str(product_a.id), 2)]
    # The manager can still read its sales.
    sales = client.get(f"/products/{product_a.id}/sales", headers=seed.headers(world["manager_a"]))
    assert [s["order_id"] for s in sales.json()["data"]] == [str(order.id)]


def test_deleted_product_is_hidden_from_fans_but_listed_for_managers(world, owned_products):
    product_a, product_b, _ = owned_products
    seed = world["seed"]

    delete_product(world, product_a)

    store_ids = {p["id"] for p in client.get("/products/store-page").json()["products"]}
    assert str(product_a.id) not in store_ids
    assert str(product_b.id) in store_ids
    assert client.get(f"/products/{product_a.id}/detail").status_code == 404
    assert client.get(f"/products/search/{product_a.id}").status_code == 404
    assert str(product_a.id) not in {p["id"] for p in client.get("/products/all").json()}
    filtered = client.get("/products/filter", params={"category": world["category"].name, "limit": 50})
    assert str(product_a.id) not in {p["id"] for p in filtered.json()["data"]}
    # Not recommended on another product's detail page either.
    detail_b = client.get(f"/products/{product_b.id}/detail").json()
    assert str(product_a.id) not in {r["id"] for r in detail_b["recommendations"]}

    page = client.get("/products/manager-products-page", headers=seed.headers(world["manager_a"])).json()
    active_by_id = {p["id"]: p["is_active"] for p in page["products"]}
    assert active_by_id[str(product_a.id)] is False
    form = client.get("/products/manager-product-form-page", headers=seed.headers(world["admin"])).json()
    assert {p["id"]: p["is_active"] for p in form["products"]}[str(product_b.id)] is True


def test_deleted_product_leaves_carts_and_cannot_be_added_again(world, owned_products):
    product_a, product_b, _ = owned_products
    seed = world["seed"]
    fan = seed.headers(world["fan"])
    for product in (product_a, product_b):
        assert client.post("/cart/add_cart", json={"product_id": str(product.id), "quantity": 1}, headers=fan).status_code == 200

    delete_product(world, product_a)

    assert [i["product_id"] for i in client.get("/cart/see_cart", headers=fan).json()["items"]] == [str(product_b.id)]
    again = client.post("/cart/add_cart", json={"product_id": str(product_a.id), "quantity": 1}, headers=fan)
    assert again.status_code == 404


def test_checkout_rejects_a_cart_holding_a_deactivated_product(world, owned_products):
    # Deleting through the API empties carts, so deactivate behind its back: the window between
    # checkout reading the cart and locking the products.
    product_a, _, _ = owned_products
    seed = world["seed"]
    fan = seed.headers(world["fan"])
    address = seed.address(world["fan"].id)
    assert client.post("/cart/add_cart", json={"product_id": str(product_a.id), "quantity": 1}, headers=fan).status_code == 200
    product_a.is_active = False
    seed.db.commit()

    res = client.post("/order/checkout", headers=fan, json={
        "amount": with_tax(product_a.price), "shipping_address_id": str(address.id),
        "gateway": "mock", "simulate_succ": True, "idempotency_key": str(uuid.uuid4()),
    })

    assert res.status_code == 400
    assert res.json()["code"] == "product_unavailable"
    assert seed.db.query(OrderItem).filter(OrderItem.product_id == product_a.id).count() == 0
    seed.db.query(Cart).filter(Cart.product_id == product_a.id).delete()
    seed.db.commit()


def test_reactivate_scoping_and_effect(world, owned_products):
    product_a, product_b, _ = owned_products
    seed = world["seed"]
    manager_a = seed.headers(world["manager_a"])
    delete_product(world, product_a)
    delete_product(world, product_b)

    assert client.patch(f"/products/activate/{product_b.id}", headers=manager_a).status_code == 403
    assert client.patch(f"/products/activate/{uuid.uuid4()}", headers=manager_a).status_code == 404
    assert client.patch(f"/products/activate/{product_a.id}", headers=seed.headers(world["fan"])).status_code == 403
    assert client.patch(f"/products/activate/{product_a.id}", headers=manager_a).status_code == 200

    seed.db.expire_all()
    assert seed.db.get(Product, product_a.id).is_active is True
    assert seed.db.get(Product, product_b.id).is_active is False
    assert str(product_a.id) in {p["id"] for p in client.get("/products/store-page").json()["products"]}
    assert client.get(f"/products/{product_a.id}/detail").status_code == 200


def test_database_refuses_to_hard_delete_an_ordered_product(world, owned_products):
    # The backstop under the soft delete: orders_items.product_id is ON DELETE RESTRICT.
    product_a, _, _ = owned_products
    seed = world["seed"]
    order = seed.order(world["fan"].id, [(product_a, 1)])

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        seed.db.execute(sqlalchemy.text("DELETE FROM products WHERE id = :id"), {"id": product_a.id})
    seed.db.rollback()

    assert seed.db.query(OrderItem).filter(OrderItem.order_id == order.id).count() == 1


def test_category_with_products_cannot_be_deleted(world, owned_products):
    seed = world["seed"]
    admin = seed.headers(world["admin"])

    res = client.delete(f"/categories/delete/{world['category'].id}", headers=admin)
    assert res.status_code == 400
    assert res.json()["code"] == "category_in_use"
    seed.db.expire_all()
    assert all(seed.db.get(Product, p.id) is not None for p in owned_products)

    # The database refuses too, without the service check.
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        seed.db.execute(sqlalchemy.text("DELETE FROM categories WHERE id = :id"), {"id": world["category"].id})
    seed.db.rollback()


def test_empty_category_can_be_deleted(world):
    seed = world["seed"]
    empty = seed.category()

    assert client.delete(f"/categories/delete/{empty.id}", headers=seed.headers(world["admin"])).status_code == 200
