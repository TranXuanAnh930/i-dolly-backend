import uuid

from fastapi.testclient import TestClient

from app.db.models.identity import Users
from app.db.models.marketplace import Cart, Category, Product, ShippingAddress
from app.utils.hashing import hash_password
from app.utils.jwt_manager import create_access_token
from app.utils.tax import with_tax
from main import app
from tests.integration._concurrency import db_session, run_concurrently

client = TestClient(app)

# ───────────────────────────────────────────────────────────────
# What this file is for (see order_service.checkout, app/services/marketplace/
# order_service.py:79 — products are locked with with_for_update() before the
# stock check, and decremented only after payment succeeds). These tests
# exist to prove that lock actually serializes concurrent checkouts, not
# just that a single checkout works — that's already covered by
# test_orders.py's sequential tests.
#
# Two scenarios covered below:
#   1. test_concurrent_checkout_oversells_nothing — seed quantity=1, race N
#      distinct fans each checking out 1 unit. Assert exactly one succeeds
#      (200) and the rest get InsufficientStockError's mapped 400 — then
#      re-query the product and assert quantity == 0, never negative.
#   2. test_concurrent_checkout_exact_stock_all_succeed — seed quantity=N,
#      race N racers each buying 1. Assert all N succeed and final quantity
#      == 0 exactly. This is the "locks don't over-serialize or deadlock"
#      counterpart — a broken implementation could pass test 1 by simply
#      failing everyone, this one catches that.
#
# These tests caught a real regression in that lock (identity-map staleness
# from the resale-cap precheck a few lines above it silently defeated
# with_for_update() for any resale-capped product — the DB default, not an
# edge case). Fixed by order_service.py:79's .populate_existing(). Full
# writeup of the mechanism and how it was confirmed: docs/project_status.md
# §4 item 1's "Regression found and fixed" note — not duplicated here so
# there's one place to keep it current.
# ───────────────────────────────────────────────────────────────


# ───────────────────────────────────────────────────────────────
# Seed helpers — all direct DB writes via db_session(), same sessionmaker
# app/db/session.py hands the real app, not a mock. Going through the public
# API for N distinct users' carts/addresses would work too but is slower and
# adds more moving parts than a concurrency test needs — the thing under
# test is the checkout lock, not registration/cart endpoints (already
# covered elsewhere: test_auth.py, test_cart.py).
# ───────────────────────────────────────────────────────────────

# is_resale_capped is left at its DB default (true — categories.py:16) on
# purpose, not an oversight: this is what real products get unless a category
# opts out, and it's what actually reproduces the race documented below.
def create_category(name: str | None = None) -> Category:
    with db_session() as db:
        category = Category(name=name or f"cat-{uuid.uuid4()}")
        db.add(category)
        db.commit()
        db.refresh(category)
        return category


def create_product(category_id: uuid.UUID, quantity: int, price: float = 100.0) -> Product:
    with db_session() as db:
        # description="" would violate ProductRead's min_length=1 the moment any
        # OTHER integration test lists all products — this suite shares one DB
        # across the whole run (no per-test rollback), so a bad seed value here
        # doesn't just affect this file.
        product = Product(name=f"product-{uuid.uuid4()}", price=price, description="test product", quantity=quantity, category_id=category_id)
        db.add(product)
        db.commit()
        db.refresh(product)
        return product


def create_fan(email: str | None = None, password: str = "racerpass123") -> Users:
    with db_session() as db:
        user = Users(
            name="Racer", email=email or f"racer-{uuid.uuid4()}@example.com",
            hashed_password=hash_password(password), role="fan", is_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def create_shipping_address(user_id: uuid.UUID) -> ShippingAddress:
    with db_session() as db:
        address = ShippingAddress(
            user_id=user_id, address_line1="1 Test St", city="Tokyo",
            postal_code="100-0001", state="Tokyo", country="Japan",
        )
        db.add(address)
        db.commit()
        db.refresh(address)
        return address


def add_to_cart(user_id: uuid.UUID, product: Product, quantity: int = 1) -> Cart:
    """Direct insert instead of POST /cart/add_cart — same reasoning as the
    other seed helpers, this file races checkout, not the cart endpoint."""
    with db_session() as db:
        cart_row = Cart(user_id=user_id, product_id=product.id, quantity=quantity, price=product.price, total_price=product.price * quantity)
        db.add(cart_row)
        db.commit()
        db.refresh(cart_row)
        return cart_row


def auth_headers_for(user: Users) -> dict:
    """Bypasses password login (same shortcut as test_venues.py's
    admin_headers) — the thing under test is checkout's locking, not login."""
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


def checkout_payload(cart_row: Cart, address_id: uuid.UUID) -> dict:
    return {
        "amount": with_tax(cart_row.total_price),
        "shipping_address_id": str(address_id),
        "gateway": "mock",
        "simulate_succ": True,
        "idempotency_key": str(uuid.uuid4()),
    }


def make_racer(quantity_each: int, product: Product):
    """Builds one fully-seeded fan (own user, address, cart row) and returns
    a zero-arg callable that performs their checkout — this is the shape
    run_concurrently expects in its `fns` list."""
    user = create_fan()
    address = create_shipping_address(user.id)
    cart_row = add_to_cart(user.id, product, quantity=quantity_each)
    headers = auth_headers_for(user)
    payload = checkout_payload(cart_row, address.id)

    def _checkout():
        # Deliberately NOT raising on a 4xx here — for this test, a losing
        # racer's InsufficientStockError-mapped response IS the expected
        # outcome, not a thread-pool failure. Inspect
        # outcomes[i].result.status_code in the test body instead of relying
        # on ThreadOutcome.exception for this file (contrast with the
        # lottery test, where the service layer raises directly).
        return client.post("/order/checkout", json=payload, headers=headers)

    _checkout.user_id = user.id  # exposed so the test can clean this racer's Users row up afterward
    return _checkout


def get_product_quantity(product_id: uuid.UUID) -> int:
    with db_session() as db:
        return db.get(Product, product_id).quantity


# This suite shares one DB across the whole integration run — no per-test
# rollback (see tests/integration/conftest.py) — so anything seeded here
# that's left behind is visible to every test that runs after it. A leftover
# Category/Product/Users row already broke test_products.py's "list all
# products" tests and test_management_companies.py's "list companies when
# empty" test the first time this file ran without cleanup. Deletes cascade
# (products.category_id, orders_items.{order_id,product_id}, orders.user_id,
# cart.user_id, shipping_addresses.user_id, payments.user_id are all ON
# DELETE CASCADE), so deleting the category and the racer users is enough to
# remove everything a test here created.

def cleanup_category(category_id: uuid.UUID) -> None:
    with db_session() as db:
        db.query(Category).filter(Category.id == category_id).delete()
        db.commit()


def cleanup_fans(user_ids: list[uuid.UUID]) -> None:
    with db_session() as db:
        db.query(Users).filter(Users.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()


def test_concurrent_checkout_oversells_nothing():
    category = create_category()
    product = create_product(category.id, quantity=1)
    racers = [make_racer(quantity_each=1, product=product) for _ in range(3)]
    fan_ids = [r.user_id for r in racers]

    try:
        outcomes = run_concurrently(racers)
        # _checkout() returns the raw response and never raises on a 4xx (see
        # its own comment) — a losing racer's InsufficientStockError-mapped
        # response IS the expected outcome here, so assert on status codes,
        # not ThreadOutcome.exception (every outcome here has
        # succeeded=True; none of them ever throw).
        statuses = [o.result.status_code for o in outcomes]
        assert statuses.count(200) == 1
        assert statuses.count(400) == 2
        assert get_product_quantity(product.id) == 0
    finally:
        cleanup_fans(fan_ids)
        cleanup_category(category.id)


def test_concurrent_checkout_exact_stock_all_succeed():
    racer_count = 3
    category = create_category()
    product = create_product(category.id, quantity=racer_count)
    racers = [make_racer(quantity_each=1, product=product) for _ in range(racer_count)]
    fan_ids = [r.user_id for r in racers]

    try:
        outcomes = run_concurrently(racers)
        statuses = [o.result.status_code for o in outcomes]
        assert statuses.count(200) == racer_count
        assert get_product_quantity(product.id) == 0
    finally:
        cleanup_fans(fan_ids)
        cleanup_category(category.id)
