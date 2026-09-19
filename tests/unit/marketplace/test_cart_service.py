import uuid
from unittest.mock import MagicMock

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# OTHER_ID for "a second, different row", MISSING_ID for "doesn't exist".
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def make_mock_user(id=DEFAULT_ID, name="Test", email="test@example.com", is_admin=False, is_verified=True, role="fan"):
    user = MagicMock()
    user.id = id
    user.name = name
    user.email = email
    user.is_admin = is_admin
    user.is_verified = is_verified
    user.hashed_password = "$2b$12$hashedpassword"
    user.role = role  # matches Users.role's real DB default (database-design.md §3.1)
    return user

def make_mock_product(id=DEFAULT_ID, name="Phone", price=999.0, description="A phone", quantity=10, category_id=DEFAULT_ID):
    product = MagicMock()
    product.id = id
    product.name = name
    product.price = price
    product.description = description
    product.quantity = quantity
    product.category_id = category_id
    product.image_url = None
    cat = MagicMock()
    cat.id = category_id
    cat.name = "Electronics"
    cat.is_resale_capped = False
    product.category = cat
    return product

def make_mock_cart_item(id=DEFAULT_ID, user_id=DEFAULT_ID, product_id=DEFAULT_ID, quantity=2, price=500.0, total_price=1000.0):
    item = MagicMock()
    item.id = id
    item.user_id = user_id
    item.product_id = product_id
    item.quantity = quantity
    item.price = price
    item.total_price = total_price
    return item


# ───────────────────────────────────────────────────────────────
# Cart Service Tests
# ───────────────────────────────────────────────────────────────

class TestCartService:

    def test_add_to_cart_new_item(self):
        from app.db.models.marketplace import Product
        from app.schema.marketplace import CartItem
        from app.services.marketplace.cart_service import CartService

        db = MagicMock()
        mock_user = make_mock_user()
        db.get.return_value = mock_user

        mock_prod = make_mock_product(quantity=10)
        # Both the Product lookup (stock check) and the existing-cart-row
        # lookup now go through .with_for_update() — one row lock each, not
        # the same .first() called twice — so db.query(...) needs to return a
        # different mock depending on which model it's called with, or both
        # calls would collide on the same .filter().with_for_update().first().
        product_query = MagicMock()
        product_query.filter.return_value.with_for_update.return_value.first.return_value = mock_prod
        cart_query = MagicMock()
        cart_query.filter.return_value.with_for_update.return_value.first.return_value = None
        db.query.side_effect = lambda model: product_query if model is Product else cart_query

        cart_data = CartItem(quantity=2, product_id=DEFAULT_ID)
        CartService.add_to_cart(db, cart_data, DEFAULT_ID)

        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_add_to_cart_insufficient_stock(self):
        from app.db.models.marketplace import Product
        from app.schema.marketplace import CartItem
        from app.services.marketplace.cart_service import CartService

        db = MagicMock()
        db.get.return_value = make_mock_user()
        mock_prod = make_mock_product(quantity=0)
        product_query = MagicMock()
        product_query.filter.return_value.with_for_update.return_value.first.return_value = mock_prod
        db.query.side_effect = lambda model: product_query if model is Product else MagicMock()

        cart_data = CartItem(quantity=5, product_id=DEFAULT_ID)
        result = CartService.add_to_cart(db, cart_data, DEFAULT_ID)
        assert result is None

    def test_add_to_cart_user_not_found(self):
        from app.schema.marketplace import CartItem
        from app.services.marketplace.cart_service import CartService

        db = MagicMock()
        db.get.return_value = None

        cart_data = CartItem(quantity=1, product_id=DEFAULT_ID)
        result = CartService.add_to_cart(db, cart_data, MISSING_ID)
        assert result is False

    def test_see_cart_with_items(self):
        from app.services.marketplace.cart_service import CartService

        db = MagicMock()
        mock_items = [make_mock_cart_item(), make_mock_cart_item(id=OTHER_ID)]
        db.query().filter().all.return_value = mock_items

        result = CartService.see_cart(db, DEFAULT_ID)
        assert len(result.items) == 2
        assert result.total_price == 2000.0

    def test_see_cart_empty(self):
        from app.services.marketplace.cart_service import CartService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = CartService.see_cart(db, DEFAULT_ID)
        assert result is None

    def test_remove_cart_success(self):
        from app.services.marketplace.cart_service import CartService

        db = MagicMock()
        mock_cart = make_mock_cart_item()
        db.query().filter().first.return_value = mock_cart

        result = CartService.remove_cart(db, DEFAULT_ID, DEFAULT_ID)
        assert result is True
        db.delete.assert_called_once_with(mock_cart)

    def test_remove_cart_not_found(self):
        from app.services.marketplace.cart_service import CartService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = CartService.remove_cart(db, DEFAULT_ID, MISSING_ID)
        assert result is None
