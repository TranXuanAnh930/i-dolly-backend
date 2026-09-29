"""Direct-DB fixture rows for HTTP-level integration tests, plus JWT headers for any role.

Not a test module (leading underscore). Every row created here, and every row a test registers
with track() after creating it through the API, is deleted afterwards with bulk DELETEs in
reverse creation order, so Postgres' ON DELETE CASCADE removes children (orders, payments,
details, ...) that an ORM-level delete would try to null out instead.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.events import Concert, TicketType, Venue
from app.db.models.identity import Users
from app.db.models.marketplace import (
    AlbumDetail,
    Category,
    MerchDetail,
    Order,
    OrderItem,
    Product,
    ShippingAddress,
    ShippingStatus,
)
from app.db.models.talent import Group, Idol, IdolColor, ManagementCompany
from app.db.session import session as SessionLocal
from app.utils.hashing import hash_password
from app.utils.jwt_manager import create_access_token
from tests.conftest import fake_redis

# Seeded users authenticate with a minted JWT, never a password, so one bcrypt hash is enough.
_PASSWORD_HASH = hash_password("password123")


class Seed:
    def __init__(self):
        self.db = SessionLocal()
        self._created: list[tuple[type, object]] = []

    def save(self, obj):
        """Insert any model instance and register it for cleanup."""
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        self.track(type(obj), obj.id if hasattr(obj, "id") else obj.product_id)
        return obj

    def track(self, model: type, pk) -> None:
        """Register a row created elsewhere (e.g. through the API) for cleanup."""
        self._created.append((model, pk))

    # --- identity / talent

    def company(self) -> ManagementCompany:
        return self.save(ManagementCompany(name=f"company-{uuid.uuid4()}"))

    def user(self, role: str = "fan", company_id=None) -> Users:
        return self.save(Users(
            name=f"{role}-user", email=f"{role}-{uuid.uuid4()}@example.com",
            hashed_password=_PASSWORD_HASH, role=role, company_id=company_id, is_verified=True,
        ))

    @staticmethod
    def headers(user: Users) -> dict:
        return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}

    def group(self, company_id, is_active: bool = True) -> Group:
        return self.save(Group(company_id=company_id, name=f"group-{uuid.uuid4()}", is_active=is_active))

    def idol(self, company_id, group_id=None, is_active: bool = True) -> Idol:
        return self.save(Idol(company_id=company_id, group_id=group_id, name=f"idol-{uuid.uuid4()}", is_active=is_active))

    def color(self) -> IdolColor:
        return self.save(IdolColor(name=f"color-{uuid.uuid4()}", hex_code=f"#{uuid.uuid4().hex[:6]}"))

    # --- marketplace

    def category(self, is_resale_capped: bool = False) -> Category:
        return self.save(Category(name=f"category-{uuid.uuid4()}", is_resale_capped=is_resale_capped))

    def product(self, category_id, price: float = 1000.0, quantity: int = 10, name: str | None = None) -> Product:
        return self.save(Product(
            name=name or f"product-{uuid.uuid4()}", price=price, description="A product",
            quantity=quantity, category_id=category_id,
        ))

    def album(self, product_id, idol_id=None, group_id=None) -> AlbumDetail:
        return self.save(AlbumDetail(product_id=product_id, idol_id=idol_id, group_id=group_id))

    def merch(self, product_id, idol_id=None, group_id=None) -> MerchDetail:
        return self.save(MerchDetail(product_id=product_id, idol_id=idol_id, group_id=group_id))

    def address(self, user_id) -> ShippingAddress:
        return self.save(ShippingAddress(
            user_id=user_id, address_line1="1 Test St", city="Tokyo", postal_code="100-0001",
            state="Tokyo", country="Japan",
        ))

    def order(self, user_id, items: list[tuple[Product, int]], shipping_status: str | None = "pending") -> Order:
        """An already-placed order, bypassing checkout. shipping_status=None leaves no status row."""
        address = self.address(user_id)
        order = Order(
            user_id=user_id, shipping_address_id=address.id,
            total_price=sum(p.price * qty for p, qty in items),
        )
        self.db.add(order)
        self.db.flush()
        for product, qty in items:
            self.db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=qty, price=product.price))
        if shipping_status is not None:
            self.db.add(ShippingStatus(order_id=order.id, status=shipping_status))
        self.db.commit()
        self.db.refresh(order)
        self.track(Order, order.id)
        return order

    # --- events

    def venue(self) -> Venue:
        return self.save(Venue(
            name=f"venue-{uuid.uuid4()}", address="1 Test St", city="Tokyo", country="Japan", total_capacity=5000,
        ))

    def concert(self, company_id, venue_id) -> Concert:
        return self.save(Concert(
            company_id=company_id, venue_id=venue_id, title=f"concert-{uuid.uuid4()}", capacity=500,
            event_datetime=datetime.now(timezone.utc) + timedelta(days=60),
        ))

    def ticket_type(self, concert_id, sale_method: str = "direct", price: float = 100.0) -> TicketType:
        return self.save(TicketType(
            concert_id=concert_id, tier="regular", price=price, total_quantity=100, sale_method=sale_method,
        ))

    def cleanup(self) -> None:
        self.db.rollback()
        for model, pk in reversed(self._created):
            pk_col = model.__mapper__.primary_key[0]
            self.db.query(model).filter(pk_col == pk).delete(synchronize_session=False)
        self.db.commit()
        self.db.close()


@pytest.fixture
def seed():
    # Rows are written straight to the DB, bypassing the API's cache invalidation, so start from
    # an empty cache (this also clears the rate-limit counters).
    fake_redis.flushall()
    s = Seed()
    try:
        yield s
    finally:
        s.cleanup()
        fake_redis.flushall()
