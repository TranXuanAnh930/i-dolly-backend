import io
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.models.marketplace import AlbumDetail, MerchDetail, Product
from main import app

# ───────────────────────────────────────────────────────────────
# Product management over real HTTP + Postgres: creating a product together with its
# album/merch detail (company-scoped through the idol/group it's attached to), image upload,
# delete, bulk add, the company-scoped manager pages, sales history, and the public read pages.
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
    assert seed.db.get(Product, b_id) is not None
    assert seed.db.get(Product, a_id) is None


# ───────────────────────────────────────────────────────────────
# Manager pages + sales history
# ───────────────────────────────────────────────────────────────

def test_manager_products_page_scoped_by_company(world, owned_products):
    product_a, product_b, ownerless = owned_products
    ids = {str(p.id) for p in owned_products}

    def page_ids(company_id=None):
        params = {"company_id": str(company_id)} if company_id else {}
        res = client.get("/products/manager-products-page", params=params)
        assert res.status_code == 200
        return {p["id"] for p in res.json()["products"]} & ids

    assert page_ids(world["company_a"].id) == {str(product_a.id), str(ownerless.id)}
    assert page_ids(world["company_b"].id) == {str(product_b.id), str(ownerless.id)}
    assert page_ids() == ids


def test_manager_product_form_page_includes_reference_data(world, owned_products):
    product_a, _, ownerless = owned_products
    res = client.get("/products/manager-product-form-page", params={"company_id": str(world["company_a"].id)})

    assert res.status_code == 200
    body = res.json()
    product_ids = {p["id"] for p in body["products"]}
    assert {str(product_a.id), str(ownerless.id)} <= product_ids
    assert str(owned_products[1].id) not in product_ids
    assert str(world["category"].id) in {c["id"] for c in body["categories"]}
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
