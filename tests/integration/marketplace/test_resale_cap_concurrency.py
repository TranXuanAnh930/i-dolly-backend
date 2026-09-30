import threading
import time
import uuid

from sqlalchemy import text

from app.db.models.marketplace import Order, OrderItem, Product
from app.exception.db_triggers import ResaleCapExceededError, flush_or_raise
from app.schema.marketplace import PaymentCreate
from app.services.marketplace.order_service import OrderService
from app.utils.resale import RESALE_CAP_QUANTITY
from app.utils.tax import with_tax
from tests.integration._concurrency import db_session, run_concurrently
from tests.integration.marketplace.test_orders_concurrency import (
    add_to_cart,
    cleanup_category,
    cleanup_fans,
    create_category,
    create_fan,
    create_product,
    create_shipping_address,
)

# The resale cap (RESALE_CAP_QUANTITY units of one product per fan, lifetime) is enforced twice:
# order_service.checkout checks it, and trg_orders_items_resale_cap is the DB backstop. Both read
# "how many has this fan already ordered", so two concurrent transactions for the same fan and
# product can each see the other's order as not there yet. These tests race exactly that.


def seed_prior_order(user_id: uuid.UUID, address_id: uuid.UUID, product: Product, quantity: int) -> None:
    with db_session() as db:
        order = Order(user_id=user_id, shipping_address_id=address_id, total_price=product.price * quantity)
        db.add(order)
        db.flush()
        db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=quantity, price=product.price))
        db.commit()


def ordered_quantity(user_id: uuid.UUID, product_id: uuid.UUID) -> int:
    with db_session() as db:
        rows = db.query(OrderItem.quantity).join(Order).filter(Order.user_id == user_id, OrderItem.product_id == product_id).all()
        return sum(q for (q,) in rows)


def hold_lock_until_waiting(product_id: uuid.UUID, waiters: int, racers: list) -> list:
    """Lock the product row, start the racers, and release only once `waiters` of them are
    blocked on a lock. Every racer has then read its cart and done any pre-lock work, so the
    test can't pass just because one racer finished before the other started."""
    with db_session() as blocker:
        blocker.query(Product).filter(Product.id == product_id).with_for_update().one()
        result: list = []
        runner = threading.Thread(target=lambda: result.extend(run_concurrently(racers)))
        runner.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with db_session() as probe:
                waiting = probe.execute(text(
                    "SELECT COUNT(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )).scalar()
            if waiting >= waiters:
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"only {waiting} of {waiters} racers reached the lock")
        blocker.commit()
    runner.join(timeout=30)
    return result


def test_concurrent_checkouts_by_same_fan_cannot_exceed_resale_cap():
    # Fan already owns cap-1 units; two checkouts of 1 more race. Only one may land.
    category = create_category()
    product = create_product(category.id, quantity=100)
    fan = create_fan()
    address = create_shipping_address(fan.id)
    seed_prior_order(fan.id, address.id, product, quantity=RESALE_CAP_QUANTITY - 1)
    cart_row = add_to_cart(fan.id, product, quantity=1)

    def racer():
        payment = PaymentCreate(
            amount=with_tax(cart_row.total_price), shipping_address_id=address.id,
            gateway="mock", simulate_succ=True, idempotency_key=str(uuid.uuid4()),
        )
        with db_session() as db:
            return OrderService.checkout(db, fan.id, payment).id

    try:
        outcomes = hold_lock_until_waiting(product.id, waiters=2, racers=[racer, racer])
        successes = [o for o in outcomes if o.succeeded]
        failures = [o for o in outcomes if not o.succeeded]
        assert len(successes) == 1
        assert len(failures) == 1
        error = failures[0].exception
        assert isinstance(error, ResaleCapExceededError), repr(error)
        # Raised by checkout's own check, not translated from the trigger: the check has to read
        # the winner's order, which it only can after waiting on the product lock.
        assert error.__cause__ is None, repr(error)
        assert ordered_quantity(fan.id, product.id) == RESALE_CAP_QUANTITY
        # The losing checkout rolled back entirely, so stock only moved once.
        assert_product_quantity(product.id, 99)
    finally:
        cleanup_fans([fan.id])
        cleanup_category(category.id)


def test_concurrent_checkouts_by_different_fans_are_capped_independently():
    # The cap is per fan: serializing same-fan checkouts must not block other fans' units.
    category = create_category()
    product = create_product(category.id, quantity=100)
    fans = [create_fan() for _ in range(3)]
    racers = []
    for fan in fans:
        address = create_shipping_address(fan.id)
        cart_row = add_to_cart(fan.id, product, quantity=RESALE_CAP_QUANTITY)

        def racer(fan=fan, address=address, cart_row=cart_row):
            payment = PaymentCreate(
                amount=with_tax(cart_row.total_price), shipping_address_id=address.id,
                gateway="mock", simulate_succ=True, idempotency_key=str(uuid.uuid4()),
            )
            with db_session() as db:
                return OrderService.checkout(db, fan.id, payment).id

        racers.append(racer)

    try:
        outcomes = run_concurrently(racers)
        assert all(o.succeeded for o in outcomes), [o.exception for o in outcomes]
        for fan in fans:
            assert ordered_quantity(fan.id, product.id) == RESALE_CAP_QUANTITY
        assert_product_quantity(product.id, 100 - 3 * RESALE_CAP_QUANTITY)
    finally:
        cleanup_fans([fan.id for fan in fans])
        cleanup_category(category.id)


def test_resale_cap_trigger_holds_under_concurrent_inserts():
    # Bypasses the service (and its product lock) to prove the trigger alone is race-safe.
    # A inserts its line and holds the transaction open; B inserts while A is uncommitted.
    # Without serialization inside the trigger, B can't see A's row and both commit.
    category = create_category()
    product = create_product(category.id, quantity=100)
    fan = create_fan()
    address = create_shipping_address(fan.id)
    quantity_each = RESALE_CAP_QUANTITY - 1
    a_inserted = threading.Event()

    def insert_line(db) -> None:
        order = Order(user_id=fan.id, shipping_address_id=address.id, total_price=product.price * quantity_each)
        db.add(order)
        flush_or_raise(db)
        db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=quantity_each, price=product.price))
        flush_or_raise(db)

    def racer_a():
        with db_session() as db:
            insert_line(db)
            a_inserted.set()
            # Give B time to reach its own insert while this transaction is still open.
            time.sleep(1.0)
            db.commit()

    def racer_b():
        assert a_inserted.wait(timeout=10)
        with db_session() as db:
            insert_line(db)
            db.commit()

    try:
        outcomes = run_concurrently([racer_a, racer_b])
        assert outcomes[0].succeeded, outcomes[0].exception
        assert not outcomes[1].succeeded
        assert isinstance(outcomes[1].exception, ResaleCapExceededError)
        assert ordered_quantity(fan.id, product.id) == quantity_each
    finally:
        cleanup_fans([fan.id])
        cleanup_category(category.id)


def assert_product_quantity(product_id: uuid.UUID, expected: int) -> None:
    with db_session() as db:
        assert db.get(Product, product_id).quantity == expected
