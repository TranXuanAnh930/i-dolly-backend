import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.exception.common import BadRequestError, ForbiddenError, NotFoundError

# ─────────────────────────────────────────────────────────────
# Id sentinels — ids are UUIDs now, not autoincrementing ints.
# These are plain MagicMock-based unit tests (no real DB), so any three
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# OTHER_ID for "a second, different row", MISSING_ID for "doesn't exist".
# ─────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()
# Stand-in for any *Read schema's created_at/updated_at — real value never
# matters to these tests, only that it's a real datetime, not an
# auto-vivified MagicMock attribute a from_attributes schema can't validate.
DEFAULT_TIMESTAMP = datetime.now(timezone.utc)

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

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

# Talent/Marketplace domain helpers — company-scoped rows all need at least
# .id/.company_id/.is_active for _manager_scope_violation and the soft-delete
# checks each of these services shares.

def make_mock_manager(id=DEFAULT_ID, company_id=DEFAULT_ID, name="Manager", email="manager@example.com"):
    user = make_mock_user(id=id, name=name, email=email, role="manager")
    user.company_id = company_id
    return user

def make_mock_company(id=DEFAULT_ID, name="Nova Entertainment"):
    company = MagicMock()
    company.id = id
    company.name = name
    return company

def make_mock_group(id=DEFAULT_ID, company_id=DEFAULT_ID, name="Prism", is_active=True):
    group = MagicMock()
    group.id = id
    group.company_id = company_id
    group.name = name
    group.is_active = is_active
    group.debut_date = None
    group.description = None
    group.created_at = DEFAULT_TIMESTAMP
    group.updated_at = DEFAULT_TIMESTAMP
    return group

def make_mock_idol(id=DEFAULT_ID, company_id=DEFAULT_ID, group_id=None, color_id=None, is_active=True, name="Idol"):
    idol = MagicMock()
    idol.id = id
    idol.company_id = company_id
    idol.group_id = group_id
    idol.color_id = color_id
    idol.is_active = is_active
    idol.name = name
    idol.date_of_birth = None
    idol.hometown = None
    idol.short_intro = None
    idol.long_description = None
    idol.profile_image_url = None
    idol.created_at = DEFAULT_TIMESTAMP
    idol.updated_at = DEFAULT_TIMESTAMP
    idol.idol_positions = []
    idol.color = None
    idol.group = None
    return idol

def make_mock_color(id=DEFAULT_ID, name="Crimson", hex_code="#FF0000"):
    color = MagicMock()
    color.id = id
    color.name = name
    color.hex_code = hex_code
    return color

def make_mock_venue(id=DEFAULT_ID, name="Arena"):
    venue = MagicMock()
    venue.id = id
    venue.name = name
    venue.address = "1 Main St"
    venue.city = "Seoul"
    venue.country = "KR"
    venue.total_capacity = 1000
    venue.contact_info = None
    venue.size = "large"
    venue.created_at = DEFAULT_TIMESTAMP
    return venue

def make_mock_concert(id=DEFAULT_ID, company_id=DEFAULT_ID, venue=None):
    concert = MagicMock()
    concert.id = id
    concert.company_id = company_id
    concert.venue_id = venue.id if venue else DEFAULT_ID
    concert.title = "Concert"
    concert.description = None
    concert.capacity = 500
    concert.event_datetime = DEFAULT_TIMESTAMP
    concert.doors_open_at = None
    concert.status = "scheduled"
    concert.created_at = DEFAULT_TIMESTAMP
    concert.updated_at = DEFAULT_TIMESTAMP
    concert.venue = venue if venue else make_mock_venue(id=concert.venue_id)
    return concert

def model_get_side_effect(mapping: dict):
    """Builds a db.get(Model, id) side_effect that dispatches on the model
    class, since a plain MagicMock().get ignores call args and can't tell
    db.get(Product, ...) apart from db.get(AlbumDetail, ...) on its own."""
    def _side_effect(model, ident=None):
        return mapping.get(model)
    return _side_effect


# ─────────────────────────────────────────────────────────────
# Auth Service Tests
# ─────────────────────────────────────────────────────────────

class TestAuthService:

    def test_create_user_success(self):
        from app.schema.identity import UserCreate
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().first.return_value = None
        mock_user = MagicMock()
        mock_user.id = DEFAULT_ID
        db.add.return_value = None
        db.refresh.side_effect = lambda x: setattr(x, 'id', DEFAULT_ID)
        user_data = UserCreate(name="John", email="john@example.com", password="pass123")

        with patch("app.services.identity.auth_service.hash_password", return_value="hashed"):
            result = AuthService.create_user(db, user_data)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not False

    def test_create_user_duplicate_email(self):
        from app.schema.identity import UserCreate
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().first.return_value = make_mock_user()
        user_data = UserCreate(name="John", email="test@example.com", password="pass123")

        result = AuthService.create_user(db, user_data)
        assert result is False

    def test_authenticate_user_success(self):
        from app.services.identity.auth_service import AuthService

        mock_user = make_mock_user()
        db = MagicMock()
        db.query().filter().first.return_value = mock_user

        with patch("app.services.identity.auth_service.verify_password", return_value=True):
            result = AuthService.authenticate_user(db, "test@example.com", "password")

        assert result == mock_user

    def test_authenticate_user_wrong_password(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().first.return_value = make_mock_user()

        with patch("app.services.identity.auth_service.verify_password", return_value=False):
            result = AuthService.authenticate_user(db, "test@example.com", "wrong")

        assert result is None

    def test_authenticate_user_not_found(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = AuthService.authenticate_user(db, "nope@example.com", "password")
        assert result is None

    def test_create_tokens(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().update.return_value = 0
        mock_user = make_mock_user()

        with patch("app.services.identity.auth_service.create_access_token", return_value="access_tok"):
            result = AuthService.create_tokens(db, mock_user)

        assert "access_token" in result
        assert "refresh_token" in result
        assert result["access_token"] == "access_tok"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_verify_refresh_token_valid(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        mock_token = MagicMock()
        mock_token.revoked = False
        mock_token.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        mock_token.user_id = DEFAULT_ID
        db.query().filter().first.return_value = mock_token

        mock_user = make_mock_user()
        db.query().filter().first.side_effect = [mock_token, mock_user]

        result = AuthService.verify_refresh_token(db, "valid-token")
        # Result should be the user (from second query)
        assert result is not None

    def test_verify_refresh_token_expired(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        mock_token = MagicMock()
        mock_token.revoked = False
        mock_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.query().filter().first.return_value = mock_token

        result = AuthService.verify_refresh_token(db, "expired-token")
        assert result is None

    def test_verify_email_token_success(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        mock_user = make_mock_user()
        mock_user.is_verified = False
        db.query().filter().first.return_value = mock_user

        with patch("app.services.identity.auth_service.verify_token_and_get_user_id", return_value=DEFAULT_ID):
            result = AuthService.verify_email_token(db, "valid-email-token")

        assert result is True
        assert mock_user.is_verified is True
        db.commit.assert_called_once()

    def test_verify_email_token_invalid(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        with patch("app.services.identity.auth_service.verify_token_and_get_user_id", return_value=None):
            result = AuthService.verify_email_token(db, "invalid-token")
        assert result is None

    def test_email_verification_process(self):
        from app.services.identity.auth_service import AuthService

        mock_user = make_mock_user()

        with patch("app.services.identity.auth_service.create_email_verification_token", return_value="tok123"), \
             patch("app.services.identity.auth_service.celery_app.send_task") as mock_send_task:
            result = AuthService.email_verification_process(mock_user)

        mock_send_task.assert_called_once()
        assert mock_send_task.call_args[0][0] == "app.tasks.email.send_email"
        assert result is None

    def test_cleanup_expired_tokens(self):
        from app.services.identity.auth_service import AuthService

        db = MagicMock()
        db.query().filter().delete.return_value = 5

        result = AuthService.cleanup_expired_tokens(db)
        assert result == 5
        db.commit.assert_called_once()


# ─────────────────────────────────────────────────────────────
# Product Service Tests
# ─────────────────────────────────────────────────────────────

class TestProductService:

    def test_list_of_products(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        mock_products = [make_mock_product(), make_mock_product(id=OTHER_ID)]
        db.query().options().all.return_value = mock_products

        result = ProductService.list_of_products(db)
        assert len(result) == 2

    def test_list_of_products_empty(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.query().options().all.return_value = []

        result = ProductService.list_of_products(db)
        assert result is False

    def test_search_product_found(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        mock_prod = make_mock_product()
        db.query().options().filter().first.return_value = mock_prod

        result = ProductService.search_product(db, DEFAULT_ID)
        assert result.name == "Phone"

    def test_search_product_not_found(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.query().options().filter().first.return_value = None

        result = ProductService.search_product(db, MISSING_ID)
        assert result is False

    def test_add_product(self):
        from app.schema.marketplace import ProductCreate
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        product_data = ProductCreate(name="Laptop", price=1500.0, description="A laptop", quantity=5, category_id=DEFAULT_ID)

        ProductService.add_product(db, product_data)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_update_product_found(self):
        from app.schema.marketplace import ProductCreate
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        mock_prod = make_mock_product()
        db.get.return_value = mock_prod
        # Admin, not manager: update_product's manager-only price-lock guard
        # (docs/database-design.md's manager-CRUD rules) isn't what this
        # test is exercising, so use the role that bypasses it.
        admin = make_mock_user(role="admin")
        update_data = ProductCreate(name="Updated", price=100.0, description="Updated", quantity=5, category_id=DEFAULT_ID)

        result = ProductService.update_product(db, DEFAULT_ID, update_data, admin)
        db.commit.assert_called_once()
        assert result is not False

    def test_update_product_not_found(self):
        from app.schema.marketplace import ProductCreate
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.get.return_value = None
        admin = make_mock_user(role="admin")
        update_data = ProductCreate(name="Updated", price=100.0, description="Updated", quantity=5, category_id=DEFAULT_ID)

        result = ProductService.update_product(db, MISSING_ID, update_data, admin)
        assert result is False

    def test_delete_product_found(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        mock_prod = make_mock_product()
        db.get.return_value = mock_prod
        admin = make_mock_user(role="admin")

        ProductService.delete_product(db, DEFAULT_ID, admin)
        db.delete.assert_called_once_with(mock_prod)
        db.commit.assert_called_once()

    def test_delete_product_not_found(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.get.return_value = None
        admin = make_mock_user(role="admin")

        result = ProductService.delete_product(db, MISSING_ID, admin)
        assert result is False

    def test_pagination_process(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        mock_products = [make_mock_product()]
        db.query().offset().limit().all.return_value = mock_products

        result = ProductService.pagination_process(db, page=1, limit=10)
        assert len(result) == 1


# ─────────────────────────────────────────────────────────────
# Cart Service Tests
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# User Service Tests
# ─────────────────────────────────────────────────────────────

class TestUserService:

    def test_change_password_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user()

        with patch("app.services.identity.user_service.verify_password", return_value=True), \
             patch("app.services.identity.user_service.hash_password", return_value="new_hashed"):
            result = UserService.change_password_process(db, mock_user, "oldpass", "newpass")

        assert result is True
        db.commit.assert_called_once()

    def test_change_password_wrong_old(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user()

        with patch("app.services.identity.user_service.verify_password", return_value=False):
            result = UserService.change_password_process(db, mock_user, "wrong", "newpass")

        assert result is None

    def test_promote_admin_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user(is_admin=False)
        db.get.return_value = mock_user

        result = UserService.promote_admin(db, DEFAULT_ID)
        assert result is True
        assert mock_user.is_admin is True

    def test_promote_admin_already_admin(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user(is_admin=True)
        db.get.return_value = mock_user

        result = UserService.promote_admin(db, DEFAULT_ID)
        assert result is False

    def test_promote_admin_user_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.get.return_value = None

        result = UserService.promote_admin(db, MISSING_ID)
        assert result is None

    def test_create_manager_success(self):
        from app.schema.identity import ManagerCreate
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None  # no existing user with this email
        db.get.return_value = MagicMock()  # company exists
        data = ManagerCreate(name="Manager", email="manager@example.com", password="pass123", company_id=DEFAULT_ID)

        result = UserService.create_manager_user(db, data)
        assert result not in ("email_taken", "company_not_found")
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_create_manager_email_taken(self):
        from app.schema.identity import ManagerCreate
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = make_mock_user()
        data = ManagerCreate(name="Manager", email="manager@example.com", password="pass123", company_id=DEFAULT_ID)

        result = UserService.create_manager_user(db, data)
        assert result == "email_taken"

    def test_create_manager_company_not_found(self):
        from app.schema.identity import ManagerCreate
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None
        db.get.return_value = None
        data = ManagerCreate(name="Manager", email="manager@example.com", password="pass123", company_id=MISSING_ID)

        result = UserService.create_manager_user(db, data)
        assert result == "company_not_found"

    def test_revoke_token_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_token = MagicMock()
        mock_token.revoked = False
        db.query().filter().first.return_value = mock_token

        result = UserService.revoke_token(db, "token123")
        assert result is True
        assert mock_token.revoked is True

    def test_revoke_token_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = UserService.revoke_token(db, "nonexistent")
        assert result is False

    def test_delete_user_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user()
        db.get.return_value = mock_user

        result = UserService.delete_user(db, DEFAULT_ID)
        assert result is True
        db.delete.assert_called_once_with(mock_user)

    def test_delete_user_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.get.return_value = None

        result = UserService.delete_user(db, MISSING_ID)
        assert result is None

    def test_reset_password_process_success(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        mock_user = make_mock_user()
        db.query().filter().first.return_value = mock_user
        bg_tasks = MagicMock()

        with patch("app.services.identity.user_service.create_password_reset_token", return_value="reset_tok"):
            result = UserService.reset_password_process(db, "test@example.com", bg_tasks)

        assert result is True
        bg_tasks.add_task.assert_called_once()

    def test_reset_password_process_email_not_found(self):
        from app.services.identity.user_service import UserService

        db = MagicMock()
        db.query().filter().first.return_value = None
        bg_tasks = MagicMock()

        # Always returns True, matched user or not — the router gives the
        # same generic response either way so this can't be used to
        # enumerate registered emails (user_service.py's own comment).
        result = UserService.reset_password_process(db, "nope@example.com", bg_tasks)
        assert result is True
        bg_tasks.add_task.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Category Service Tests
# ─────────────────────────────────────────────────────────────

class TestCategoryService:

    def test_add_category(self):
        from app.schema.marketplace import CategoryBase
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        cat_data = CategoryBase(name="Electronics")

        CategoryService.add_categories(db, cat_data)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_get_categories(self):
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.query().all.return_value = [MagicMock(id=DEFAULT_ID, name="Electronics")]

        result = CategoryService.get_categories(db)
        assert len(result) == 1

    def test_get_categories_empty(self):
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.query().all.return_value = []

        result = CategoryService.get_categories(db)
        assert result is False

    def test_update_category_success(self):
        from app.schema.marketplace import CategoryUpdate
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        mock_cat = MagicMock()
        db.get.return_value = mock_cat

        result = CategoryService.update_category(db, DEFAULT_ID, CategoryUpdate(name="Updated"))
        assert result is not False
        db.commit.assert_called_once()

    def test_update_category_not_found(self):
        from app.schema.marketplace import CategoryUpdate
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.get.return_value = None

        result = CategoryService.update_category(db, MISSING_ID, CategoryUpdate(name="Nope"))
        assert result is False

    def test_delete_category_success(self):
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        mock_cat = MagicMock()
        db.get.return_value = mock_cat

        result = CategoryService.delete_category(db, DEFAULT_ID)
        assert result is True
        db.delete.assert_called_once()

    def test_delete_category_not_found(self):
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.get.return_value = None

        result = CategoryService.delete_category(db, MISSING_ID)
        assert result is False


# ─────────────────────────────────────────────────────────────
# Shipping Service Tests
# ─────────────────────────────────────────────────────────────

class TestShippingService:

    def test_create_shipping_address(self):
        from app.schema.marketplace import ShippingBase
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        data = ShippingBase(
            address_line1="123 Main St", city="Mumbai",
            postal_code="400001", state="MH", country="India"
        )

        ShippingService.create_shipping_address(db, DEFAULT_ID, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_fetch_address_found(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        db.query().filter().all.return_value = [MagicMock()]

        result = ShippingService.fetch_address(db, DEFAULT_ID)
        assert result is not None

    def test_fetch_address_empty(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = ShippingService.fetch_address(db, DEFAULT_ID)
        assert result is None

    def test_delete_address_success(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        mock_addr = MagicMock()
        db.query().filter().first.return_value = mock_addr

        result = ShippingService.delete_address(db, DEFAULT_ID, DEFAULT_ID)
        assert result is True
        db.delete.assert_called_once()

    def test_delete_address_not_found(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = ShippingService.delete_address(db, DEFAULT_ID, MISSING_ID)
        assert result is None


# ─────────────────────────────────────────────────────────────
# Payment Service Tests (mock gateway only — real gateway integration is
# deferred to a later phase)
# ─────────────────────────────────────────────────────────────

class TestPaymentService:

    def test_create_mock_payment_success(self):
        from app.schema.marketplace import PaymentCreate, PaymentGateway
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        def _refresh(obj):
            obj.id = DEFAULT_ID
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
        db.refresh.side_effect = _refresh
        order = MagicMock()
        order.id = DEFAULT_ID
        order.user_id = DEFAULT_ID
        order.total_price = 1000
        data = PaymentCreate(amount=1000, shipping_address_id=DEFAULT_ID, gateway=PaymentGateway.mock, simulate_succ=True, idempotency_key=uuid.uuid4())

        result = PaymentService.create_payment(db, DEFAULT_ID, order, data)
        assert result is not False
        db.add.assert_called()
        # Deliberately does not commit (payment_service.create_payment's own
        # comment) — the caller commits once, alongside the order/shipment
        # writes it made in the same transaction.
        db.flush.assert_called()

    def test_create_mock_payment_failure(self):
        from app.schema.marketplace import PaymentCreate, PaymentGateway
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        def _refresh(obj):
            obj.id = DEFAULT_ID
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
        db.refresh.side_effect = _refresh
        order = MagicMock()
        order.id = DEFAULT_ID
        data = PaymentCreate(amount=1000, shipping_address_id=DEFAULT_ID, gateway=PaymentGateway.mock, simulate_succ=False, idempotency_key=uuid.uuid4())

        # simulate_succ=False still returns the (failed-status) Payment row —
        # only an unsupported gateway returns False.
        result = PaymentService.create_payment(db, DEFAULT_ID, order, data)
        assert result is not False

    def test_fetch_payment_status_found(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        mock_payment = MagicMock()
        db.query().filter().first.return_value = mock_payment

        result = PaymentService.fetch_payment_status(db, DEFAULT_ID, DEFAULT_ID)
        assert result == mock_payment

    def test_fetch_payment_status_not_found(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = PaymentService.fetch_payment_status(db, DEFAULT_ID, MISSING_ID)
        assert result is None

    def test_fetch_all_payments(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        db.query().filter().all.return_value = [MagicMock(), MagicMock()]

        result = PaymentService.fetch_all_payments(db, DEFAULT_ID)
        assert len(result) == 2

    def test_fetch_all_payments_empty(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = PaymentService.fetch_all_payments(db, DEFAULT_ID)
        assert result is None


# ─────────────────────────────────────────────────────────────
# Talent domain: Management Company / Idol Color / Position Service Tests
# ─────────────────────────────────────────────────────────────

class TestManagementCompanyService:

    def test_add_company_success(self):
        from app.schema.talent import ManagementCompanyCreate
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        data = ManagementCompanyCreate(name="Nova Entertainment")

        result = ManagementCompanyService.add_company(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not False

    def test_get_companies_found(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.query().all.return_value = [make_mock_company()]

        result = ManagementCompanyService.get_companies(db)
        assert len(result) == 1

    def test_get_companies_empty(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.query().all.return_value = []

        result = ManagementCompanyService.get_companies(db)
        assert result is False

    def test_get_company_found(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        mock_company = make_mock_company()
        db.get.return_value = mock_company

        result = ManagementCompanyService.get_company(db, DEFAULT_ID)
        assert result == mock_company

    def test_get_company_not_found(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.get.return_value = None

        result = ManagementCompanyService.get_company(db, MISSING_ID)
        assert result is None

    def test_update_company_success(self):
        from app.schema.talent import ManagementCompanyBase
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.get.return_value = make_mock_company()
        data = ManagementCompanyBase(name="Renamed", description="New desc", contact_email="a@b.com")

        result = ManagementCompanyService.update_company(db, DEFAULT_ID, data)
        db.commit.assert_called_once()
        assert result is not False
        assert result.name == "Renamed"

    def test_update_company_not_found(self):
        from app.schema.talent import ManagementCompanyBase
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.get.return_value = None
        data = ManagementCompanyBase(name="Renamed")

        result = ManagementCompanyService.update_company(db, MISSING_ID, data)
        assert result is False

    def test_delete_company_success(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        mock_company = make_mock_company()
        db.get.return_value = mock_company

        result = ManagementCompanyService.delete_company(db, DEFAULT_ID)
        db.delete.assert_called_once_with(mock_company)
        db.commit.assert_called_once()
        assert result is True

    def test_delete_company_not_found(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.get.return_value = None

        result = ManagementCompanyService.delete_company(db, MISSING_ID)
        assert result is False


class TestIdolColorService:

    def test_add_idol_color_success(self):
        from app.schema.talent import IdolColorCreate
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        data = IdolColorCreate(name="Sakura Pink", hex_code="#FFB7C5")

        result = IdolColorService.add_idol_color(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not False

    def test_get_idol_colors_found(self):
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = IdolColorService.get_idol_colors(db)
        assert len(result) == 1

    def test_get_idol_colors_empty(self):
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.query().all.return_value = []

        result = IdolColorService.get_idol_colors(db)
        assert result is False

    def test_update_idol_color_success(self):
        from app.schema.talent import IdolColorBase
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.get.return_value = MagicMock()
        data = IdolColorBase(name="Midnight Blue", hex_code="#191970")

        result = IdolColorService.update_idol_color(db, DEFAULT_ID, data)
        db.commit.assert_called_once()
        assert result is not False

    def test_update_idol_color_not_found(self):
        from app.schema.talent import IdolColorBase
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.get.return_value = None
        data = IdolColorBase(name="Midnight Blue", hex_code="#191970")

        result = IdolColorService.update_idol_color(db, MISSING_ID, data)
        assert result is False

    def test_delete_idol_color_success(self):
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.get.return_value = MagicMock()

        result = IdolColorService.delete_idol_color(db, DEFAULT_ID)
        db.delete.assert_called_once()
        db.commit.assert_called_once()
        assert result is True

    def test_delete_idol_color_not_found(self):
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.get.return_value = None

        result = IdolColorService.delete_idol_color(db, MISSING_ID)
        assert result is False


class TestPositionService:

    def test_add_position_success(self):
        from app.schema.talent import PositionCreate
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        data = PositionCreate(name="Center")

        result = PositionService.add_position(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not False

    def test_get_positions_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = PositionService.get_positions(db)
        assert len(result) == 1

    def test_get_positions_empty(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().all.return_value = []

        result = PositionService.get_positions(db)
        assert result is False

    def test_update_position_success(self):
        from app.schema.talent import PositionBase
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = MagicMock()
        data = PositionBase(name="Leader")

        result = PositionService.update_position(db, DEFAULT_ID, data)
        db.commit.assert_called_once()
        assert result is not False

    def test_update_position_not_found(self):
        from app.schema.talent import PositionBase
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = None
        data = PositionBase(name="Leader")

        result = PositionService.update_position(db, MISSING_ID, data)
        assert result is False

    def test_delete_position_success(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = MagicMock()

        result = PositionService.delete_position(db, DEFAULT_ID)
        db.delete.assert_called_once()
        db.commit.assert_called_once()
        assert result is True

    def test_delete_position_not_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = None

        result = PositionService.delete_position(db, MISSING_ID)
        assert result is False

    # --- idol_positions join table ---

    def test_assign_idol_position_success(self):
        from app.db.models.talent import Idol, IdolPosition, Position
        from app.schema.talent import IdolPositionAssign
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        mock_position = MagicMock()
        db.get.side_effect = model_get_side_effect({Idol: mock_idol, Position: mock_position, IdolPosition: None})
        current_user = make_mock_user(role="admin")
        data = IdolPositionAssign(idol_id=DEFAULT_ID, position_id=DEFAULT_ID, is_primary=True)

        result = PositionService.assign_idol_position(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_assign_idol_position_idol_or_position_not_found(self):
        from app.db.models.talent import Idol, Position
        from app.schema.talent import IdolPositionAssign
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Idol: None, Position: MagicMock()})
        current_user = make_mock_user(role="admin")
        data = IdolPositionAssign(idol_id=MISSING_ID, position_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            PositionService.assign_idol_position(db, data, current_user)

    def test_assign_idol_position_forbidden(self):
        from app.db.models.talent import Idol, Position
        from app.schema.talent import IdolPositionAssign
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({Idol: mock_idol, Position: MagicMock()})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = IdolPositionAssign(idol_id=DEFAULT_ID, position_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            PositionService.assign_idol_position(db, data, current_user)

    def test_assign_idol_position_conflict(self):
        from app.db.models.talent import Idol, IdolPosition, Position
        from app.schema.talent import IdolPositionAssign
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({
            Idol: mock_idol, Position: MagicMock(), IdolPosition: MagicMock(),
        })
        current_user = make_mock_user(role="admin")
        data = IdolPositionAssign(idol_id=DEFAULT_ID, position_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            PositionService.assign_idol_position(db, data, current_user)

    def test_get_idol_positions_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().filter().all.return_value = [MagicMock()]

        result = PositionService.get_idol_positions(db, DEFAULT_ID)
        assert len(result) == 1

    def test_get_idol_positions_empty(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = PositionService.get_idol_positions(db, DEFAULT_ID)
        assert result is False

    def test_get_all_idol_positions_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().all.return_value = [MagicMock(), MagicMock()]

        result = PositionService.get_all_idol_positions(db)
        assert len(result) == 2

    def test_get_all_idol_positions_empty(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().all.return_value = []

        result = PositionService.get_all_idol_positions(db)
        assert result is False

    def test_update_idol_position_primary_success(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        link = MagicMock()
        link.idol.company_id = DEFAULT_ID
        db.get.return_value = link
        current_user = make_mock_user(role="admin")

        result = PositionService.update_idol_position_primary(db, DEFAULT_ID, DEFAULT_ID, True, current_user)
        assert result == link
        assert link.is_primary is True
        db.commit.assert_called_once()

    def test_update_idol_position_primary_not_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            PositionService.update_idol_position_primary(db, MISSING_ID, MISSING_ID, True, current_user)

    def test_update_idol_position_primary_forbidden(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        link = MagicMock()
        link.idol.company_id = OTHER_ID
        db.get.return_value = link
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            PositionService.update_idol_position_primary(db, DEFAULT_ID, DEFAULT_ID, True, current_user)

    def test_remove_idol_position_success(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        link = MagicMock()
        link.idol.company_id = DEFAULT_ID
        db.get.return_value = link
        current_user = make_mock_user(role="admin")

        result = PositionService.remove_idol_position(db, DEFAULT_ID, DEFAULT_ID, current_user)
        db.delete.assert_called_once_with(link)
        db.commit.assert_called_once()
        assert result is link

    def test_remove_idol_position_not_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            PositionService.remove_idol_position(db, MISSING_ID, MISSING_ID, current_user)

    def test_remove_idol_position_forbidden(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        link = MagicMock()
        link.idol.company_id = OTHER_ID
        db.get.return_value = link
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            PositionService.remove_idol_position(db, DEFAULT_ID, DEFAULT_ID, current_user)


# ─────────────────────────────────────────────────────────────
# Talent domain: Group Service Tests
# ─────────────────────────────────────────────────────────────

class TestGroupService:

    def test_add_group_success(self):
        from app.schema.talent import GroupCreate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_company()
        current_user = make_mock_user(role="admin")
        data = GroupCreate(name="Prism Sirens", company_id=DEFAULT_ID)

        result = GroupService.add_group(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_group_forbidden(self):
        from app.schema.talent import GroupCreate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        current_user = make_mock_manager(company_id=OTHER_ID)
        data = GroupCreate(name="Prism Sirens", company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GroupService.add_group(db, data, current_user)
        db.add.assert_not_called()

    def test_add_group_company_not_found(self):
        from app.schema.talent import GroupCreate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")
        data = GroupCreate(name="Prism Sirens", company_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            GroupService.add_group(db, data, current_user)

    def test_get_groups_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().filter().all.return_value = [make_mock_group()]

        result = GroupService.get_groups(db)
        assert len(result) == 1

    def test_get_groups_empty(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = GroupService.get_groups(db)
        assert result is False

    def test_get_group(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group()
        db.get.return_value = mock_group

        result = GroupService.get_group(db, DEFAULT_ID)
        assert result == mock_group

    def test_update_group_success(self):
        from app.schema.talent import GroupUpdate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(company_id=DEFAULT_ID)
        current_user = make_mock_user(role="admin")
        data = GroupUpdate(name="Renamed Group")

        result = GroupService.update_group(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_group_not_found(self):
        from app.schema.talent import GroupUpdate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")
        data = GroupUpdate(name="Renamed Group")

        with pytest.raises(NotFoundError):
            GroupService.update_group(db, MISSING_ID, data, current_user)

    def test_update_group_forbidden(self):
        from app.schema.talent import GroupUpdate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = GroupUpdate(name="Renamed Group")

        with pytest.raises(ForbiddenError):
            GroupService.update_group(db, DEFAULT_ID, data, current_user)

    def test_delete_group_success(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group(company_id=DEFAULT_ID, is_active=True)
        db.get.return_value = mock_group
        current_user = make_mock_user(role="admin")

        result = GroupService.delete_group(db, DEFAULT_ID, current_user)
        assert result is mock_group
        assert mock_group.is_active is False
        db.commit.assert_called_once()
        db.delete.assert_not_called()  # soft delete, not a hard db.delete()

    def test_delete_group_not_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            GroupService.delete_group(db, MISSING_ID, current_user)

    def test_delete_group_forbidden(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GroupService.delete_group(db, DEFAULT_ID, current_user)

    def test_reactivate_group_success(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.return_value = mock_group
        current_user = make_mock_user(role="admin")

        result = GroupService.reactivate_group(db, DEFAULT_ID, current_user)
        assert mock_group.is_active is True
        db.commit.assert_called_once()
        assert result is not None

    def test_reactivate_group_not_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            GroupService.reactivate_group(db, MISSING_ID, current_user)

    def test_reactivate_group_forbidden(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GroupService.reactivate_group(db, DEFAULT_ID, current_user)

    def test_get_groups_page_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group()
        db.query().filter().all.return_value = [mock_group]
        db.query().filter().group_by().all.return_value = [(mock_group.id, 3)]

        result = GroupService.get_groups_page(db)
        assert len(result.groups) == 1
        assert result.groups[0].id == mock_group.id
        assert mock_group.member_count == 3

    def test_get_groups_page_empty(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = GroupService.get_groups_page(db)
        assert result is False

    def test_get_group_detail_found(self):
        from app.schema.marketplace import ArtistRef, ProductCard
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group(is_active=True)
        mock_idol = make_mock_idol()
        mock_concert = make_mock_concert()
        mock_product = MagicMock()
        db.get.return_value = mock_group
        db.query().options().filter().all.return_value = [mock_idol]  # members
        db.query().join().filter().options().distinct().order_by().all.return_value = [mock_concert]  # events
        db.query().options().all.return_value = [mock_product]  # all_products

        mock_card = ProductCard(
            id=DEFAULT_ID, name="Hoodie", price=10.0, description="d", quantity=1,
            category="Merch", artist=ArtistRef(type="group", id=DEFAULT_ID, name="Prism"),
        )
        with patch(
            "app.services.marketplace.product_service.ProductService._build_product_cards",
            return_value=[mock_card],
        ):
            result = GroupService.get_group_detail(db, DEFAULT_ID)

        assert result.group.id == mock_group.id
        assert len(result.members) == 1
        assert result.members[0].id == mock_idol.id
        assert len(result.events) == 1
        assert result.events[0].id == mock_concert.id
        assert len(result.products) == 1

    def test_get_group_detail_not_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None

        result = GroupService.get_group_detail(db, MISSING_ID)
        assert result is False

    def test_get_group_detail_inactive(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(is_active=False)

        result = GroupService.get_group_detail(db, DEFAULT_ID)
        assert result is False

    def test_get_manager_groups_page(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().all.return_value = [make_mock_group()]

        result = GroupService.get_manager_groups_page(db)
        assert len(result.groups) == 1

    def test_get_manager_groups_page_empty_is_not_404(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().all.return_value = []

        # Manager/admin settings pages deliberately never sentinel-False on
        # empty — a fresh company legitimately has zero groups.
        result = GroupService.get_manager_groups_page(db)
        assert result.groups == []


# ─────────────────────────────────────────────────────────────
# Talent domain: Idol Service Tests
# ─────────────────────────────────────────────────────────────

class TestIdolService:

    def test_add_idol_success(self):
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = make_mock_company()
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID)

        result = IdolService.add_idol(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_idol_forbidden(self):
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        current_user = make_mock_manager(company_id=OTHER_ID)
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            IdolService.add_idol(db, data, current_user)
        db.add.assert_not_called()

    def test_add_idol_company_not_found(self):
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            IdolService.add_idol(db, data, current_user)

    def test_add_idol_group_not_found(self):
        from app.db.models.talent import Group, ManagementCompany
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({ManagementCompany: make_mock_company(), Group: None})
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID, group_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            IdolService.add_idol(db, data, current_user)

    def test_add_idol_color_not_found(self):
        from app.db.models.talent import IdolColor, ManagementCompany
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({ManagementCompany: make_mock_company(), IdolColor: None})
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID, color_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            IdolService.add_idol(db, data, current_user)

    def test_add_idol_company_mismatch(self):
        from app.db.models.talent import Group, ManagementCompany
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mismatched_group = make_mock_group(company_id=OTHER_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({ManagementCompany: make_mock_company(), Group: mismatched_group})
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID, group_id=OTHER_ID)

        with pytest.raises(BadRequestError):
            IdolService.add_idol(db, data, current_user)

    def test_add_idol_group_inactive(self):
        from app.db.models.talent import Group, ManagementCompany
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        inactive_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({ManagementCompany: make_mock_company(), Group: inactive_group})
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID, group_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            IdolService.add_idol(db, data, current_user)

    def test_get_idols_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().filter().all.return_value = [make_mock_idol()]

        result = IdolService.get_idols(db)
        assert len(result) == 1

    def test_get_idols_empty(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = IdolService.get_idols(db)
        assert result is False

    def test_get_idol(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol()
        db.get.return_value = mock_idol

        result = IdolService.get_idol(db, DEFAULT_ID)
        assert result == mock_idol

    def test_update_idol_success(self):
        from app.db.models.talent import Idol, ManagementCompany
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, group_id=None)
        db.get.side_effect = model_get_side_effect({Idol: mock_idol, ManagementCompany: make_mock_company()})
        current_user = make_mock_user(role="admin")
        data = IdolUpdate(name="Renamed Idol")

        result = IdolService.update_idol(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_idol_not_found(self):
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")
        data = IdolUpdate(name="Renamed Idol")

        with pytest.raises(NotFoundError):
            IdolService.update_idol(db, MISSING_ID, data, current_user)

    def test_update_idol_forbidden(self):
        from app.db.models.talent import Idol
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = IdolUpdate(name="Renamed Idol")

        with pytest.raises(ForbiddenError):
            IdolService.update_idol(db, DEFAULT_ID, data, current_user)

    def test_update_idol_company_mismatch(self):
        from app.db.models.talent import Group, Idol, ManagementCompany
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, group_id=None)
        mismatched_group = make_mock_group(company_id=OTHER_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({
            Idol: mock_idol, ManagementCompany: make_mock_company(), Group: mismatched_group,
        })
        current_user = make_mock_user(role="admin")
        data = IdolUpdate(name="Renamed Idol", group_id=OTHER_ID)

        with pytest.raises(BadRequestError):
            IdolService.update_idol(db, DEFAULT_ID, data, current_user)

    def test_update_idol_group_inactive_blocks_new_assignment(self):
        from app.db.models.talent import Group, Idol, ManagementCompany
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        new_group_id = uuid.uuid4()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, group_id=OTHER_ID)  # currently in OTHER_ID
        inactive_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({
            Idol: mock_idol, ManagementCompany: make_mock_company(), Group: inactive_group,
        })
        current_user = make_mock_user(role="admin")
        data = IdolUpdate(name="Renamed Idol", group_id=new_group_id)  # moving INTO a deactivated group

        with pytest.raises(BadRequestError):
            IdolService.update_idol(db, DEFAULT_ID, data, current_user)

    def test_update_idol_group_inactive_allows_unchanged_group(self):
        from app.db.models.talent import Group, Idol, ManagementCompany
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        same_group_id = uuid.uuid4()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, group_id=same_group_id)
        inactive_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({
            Idol: mock_idol, ManagementCompany: make_mock_company(), Group: inactive_group,
        })
        current_user = make_mock_user(role="admin")
        # Full-replace PUT resending the idol's existing (now-deactivated) group_id
        # unchanged — not a new assignment, must not be blocked.
        data = IdolUpdate(name="Renamed Idol", group_id=same_group_id)

        result = IdolService.update_idol(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_delete_idol_success(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=True)
        db.get.return_value = mock_idol
        current_user = make_mock_user(role="admin")

        result = IdolService.delete_idol(db, DEFAULT_ID, current_user)
        assert result is mock_idol
        assert mock_idol.is_active is False
        db.delete.assert_not_called()  # soft delete

    def test_delete_idol_not_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            IdolService.delete_idol(db, MISSING_ID, current_user)

    def test_delete_idol_forbidden(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = make_mock_idol(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            IdolService.delete_idol(db, DEFAULT_ID, current_user)

    def test_reactivate_idol_success(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=False)
        db.get.return_value = mock_idol
        current_user = make_mock_user(role="admin")

        result = IdolService.reactivate_idol(db, DEFAULT_ID, current_user)
        assert mock_idol.is_active is True
        assert result is not None

    def test_reactivate_idol_not_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            IdolService.reactivate_idol(db, MISSING_ID, current_user)

    def test_reactivate_idol_forbidden(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = make_mock_idol(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            IdolService.reactivate_idol(db, DEFAULT_ID, current_user)

    def test_set_idol_image_success(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.return_value = mock_idol
        current_user = make_mock_user(role="admin")

        IdolService.set_idol_image(db, DEFAULT_ID, "https://cdn.example.com/idol.png", current_user)
        assert mock_idol.profile_image_url == "https://cdn.example.com/idol.png"
        db.commit.assert_called_once()

    def test_set_idol_image_not_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            IdolService.set_idol_image(db, MISSING_ID, "https://cdn.example.com/idol.png", current_user)

    def test_set_idol_image_forbidden(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = make_mock_idol(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            IdolService.set_idol_image(db, DEFAULT_ID, "https://cdn.example.com/idol.png", current_user)

    def test_get_members_page_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().options().filter().all.return_value = [make_mock_idol()]
        db.query().filter().all.return_value = [make_mock_group()]

        result = IdolService.get_members_page(db)
        assert len(result.idols) == 1
        assert len(result.groups) == 1

    def test_get_members_page_empty(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().options().filter().all.return_value = []

        result = IdolService.get_members_page(db)
        assert result is False

    def test_get_idol_detail_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(group_id=OTHER_ID)
        mock_group = make_mock_group(id=OTHER_ID)
        sibling = make_mock_idol(id=uuid.uuid4(), group_id=OTHER_ID)
        db.query().options().filter().first.return_value = mock_idol
        db.get.return_value = mock_group
        db.query().filter().filter().options().all.return_value = [sibling]

        result = IdolService.get_idol_detail(db, DEFAULT_ID)
        assert result.idol.id == mock_idol.id
        assert result.group.id == mock_group.id
        assert len(result.siblings) == 1
        assert result.siblings[0].id == sibling.id

    def test_get_idol_detail_not_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().options().filter().first.return_value = None

        result = IdolService.get_idol_detail(db, MISSING_ID)
        assert result is False

    def test_get_idol_detail_no_group_solo_idol(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(group_id=None)
        db.query().options().filter().first.return_value = mock_idol
        db.query().filter().filter().options().all.return_value = []

        result = IdolService.get_idol_detail(db, DEFAULT_ID)
        assert result.idol.id == mock_idol.id
        assert result.group is None
        db.get.assert_not_called()  # no group_id -> no Group lookup at all

    def test_get_manager_idols_page(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        idols = [make_mock_idol()]
        groups = [make_mock_group()]
        db.query().all.side_effect = [idols, groups]

        result = IdolService.get_manager_idols_page(db)
        assert len(result.idols) == 1
        assert result.idols[0].id == idols[0].id
        assert len(result.groups) == 1
        assert result.groups[0].id == groups[0].id

    def test_get_manager_idol_form_page(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        idols = [make_mock_idol()]
        groups = [make_mock_group()]
        colors = [make_mock_color()]
        db.query().all.side_effect = [idols, groups, colors]

        result = IdolService.get_manager_idol_form_page(db)
        assert len(result.idols) == 1
        assert len(result.groups) == 1
        assert len(result.colors) == 1
        assert result.colors[0].id == colors[0].id


# ─────────────────────────────────────────────────────────────
# Marketplace domain: Album Detail Service Tests
# ─────────────────────────────────────────────────────────────

class TestAlbumDetailService:

    def test_add_album_detail_success_with_idol(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: None, Idol: mock_idol})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID, track_count=10)

        result = AlbumDetailService.add_album_detail(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_album_detail_success_with_group(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Group
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_group = make_mock_group(company_id=DEFAULT_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: None, Group: mock_group})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=DEFAULT_ID, group_id=DEFAULT_ID)

        result = AlbumDetailService.add_album_detail(db, data, current_user)
        assert result is not None

    def test_add_album_detail_product_not_found(self):
        from app.db.models.marketplace import Product
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: None})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=MISSING_ID, idol_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            AlbumDetailService.add_album_detail(db, data, current_user)

    def test_add_album_detail_conflict(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: MagicMock()})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            AlbumDetailService.add_album_detail(db, data, current_user)

    def test_add_album_detail_artist_inactive(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        inactive_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: None, Idol: inactive_idol})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            AlbumDetailService.add_album_detail(db, data, current_user)

    def test_add_album_detail_forbidden(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=OTHER_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: None, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = AlbumDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            AlbumDetailService.add_album_detail(db, data, current_user)

    def test_get_album_detail_found(self):
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock()
        db.get.return_value = mock_album

        result = AlbumDetailService.get_album_detail(db, DEFAULT_ID)
        assert result == mock_album

    def test_get_album_detail_not_found(self):
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.return_value = None

        result = AlbumDetailService.get_album_detail(db, MISSING_ID)
        assert result is None

    def test_get_album_details_found(self):
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = AlbumDetailService.get_album_details(db)
        assert len(result) == 1

    def test_get_album_details_empty(self):
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.query().all.return_value = []

        result = AlbumDetailService.get_album_details(db)
        assert result is False

    def test_update_album_detail_success(self):
        from app.db.models.marketplace import AlbumDetail
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailUpdate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailUpdate(track_count=12)

        result = AlbumDetailService.update_album_detail(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_album_detail_not_found(self):
        from app.db.models.marketplace import AlbumDetail
        from app.schema.marketplace import AlbumDetailUpdate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({AlbumDetail: None})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailUpdate(track_count=12)

        with pytest.raises(NotFoundError):
            AlbumDetailService.update_album_detail(db, MISSING_ID, data, current_user)

    def test_update_album_detail_forbidden(self):
        from app.db.models.marketplace import AlbumDetail
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailUpdate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = AlbumDetailUpdate(track_count=12)

        with pytest.raises(ForbiddenError):
            AlbumDetailService.update_album_detail(db, DEFAULT_ID, data, current_user)

    def test_delete_album_detail_success(self):
        from app.db.models.marketplace import AlbumDetail
        from app.db.models.talent import Idol
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol})
        current_user = make_mock_user(role="admin")

        result = AlbumDetailService.delete_album_detail(db, DEFAULT_ID, current_user)
        assert result is mock_album
        db.delete.assert_called_once_with(mock_album)

    def test_delete_album_detail_not_found(self):
        from app.db.models.marketplace import AlbumDetail
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({AlbumDetail: None})
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            AlbumDetailService.delete_album_detail(db, MISSING_ID, current_user)

    def test_delete_album_detail_forbidden(self):
        from app.db.models.marketplace import AlbumDetail
        from app.db.models.talent import Idol
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            AlbumDetailService.delete_album_detail(db, DEFAULT_ID, current_user)


# ─────────────────────────────────────────────────────────────
# Marketplace domain: Merch Detail Service Tests
# ─────────────────────────────────────────────────────────────

class TestMerchDetailService:

    def test_add_merch_detail_success(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: None, Idol: mock_idol})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID, edition="Limited")

        result = MerchDetailService.add_merch_detail(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_merch_detail_product_not_found(self):
        from app.db.models.marketplace import Product
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: None})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=MISSING_ID, group_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_add_merch_detail_conflict(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: MagicMock()})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=DEFAULT_ID, group_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_add_merch_detail_color_not_found(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.db.models.talent import IdolColor
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: None, IdolColor: None})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID, color_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_add_merch_detail_artist_inactive(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.db.models.talent import Group
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        inactive_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: None, Group: inactive_group})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=DEFAULT_ID, group_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_add_merch_detail_forbidden(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=OTHER_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: None, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = MerchDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_get_merch_detail_found(self):
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock()
        db.get.return_value = mock_merch

        result = MerchDetailService.get_merch_detail(db, DEFAULT_ID)
        assert result == mock_merch

    def test_get_merch_detail_not_found(self):
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.return_value = None

        result = MerchDetailService.get_merch_detail(db, MISSING_ID)
        assert result is None

    def test_get_merch_details_found(self):
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = MerchDetailService.get_merch_details(db)
        assert len(result) == 1

    def test_get_merch_details_empty(self):
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.query().all.return_value = []

        result = MerchDetailService.get_merch_details(db)
        assert result is False

    def test_update_merch_detail_success(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol
        from app.schema.marketplace import MerchDetailUpdate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol})
        current_user = make_mock_user(role="admin")
        data = MerchDetailUpdate(edition="Reissue")

        result = MerchDetailService.update_merch_detail(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_merch_detail_not_found(self):
        from app.db.models.marketplace import MerchDetail
        from app.schema.marketplace import MerchDetailUpdate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({MerchDetail: None})
        current_user = make_mock_user(role="admin")
        data = MerchDetailUpdate(edition="Reissue")

        with pytest.raises(NotFoundError):
            MerchDetailService.update_merch_detail(db, MISSING_ID, data, current_user)

    def test_update_merch_detail_forbidden(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol
        from app.schema.marketplace import MerchDetailUpdate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = MerchDetailUpdate(edition="Reissue")

        with pytest.raises(ForbiddenError):
            MerchDetailService.update_merch_detail(db, DEFAULT_ID, data, current_user)

    def test_update_merch_detail_color_not_found(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol, IdolColor
        from app.schema.marketplace import MerchDetailUpdate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol, IdolColor: None})
        current_user = make_mock_user(role="admin")
        data = MerchDetailUpdate(edition="Reissue", color_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            MerchDetailService.update_merch_detail(db, DEFAULT_ID, data, current_user)

    def test_delete_merch_detail_success(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol})
        current_user = make_mock_user(role="admin")

        result = MerchDetailService.delete_merch_detail(db, DEFAULT_ID, current_user)
        assert result is mock_merch
        db.delete.assert_called_once_with(mock_merch)

    def test_delete_merch_detail_not_found(self):
        from app.db.models.marketplace import MerchDetail
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({MerchDetail: None})
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            MerchDetailService.delete_merch_detail(db, MISSING_ID, current_user)

    def test_delete_merch_detail_forbidden(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            MerchDetailService.delete_merch_detail(db, DEFAULT_ID, current_user)


# ─────────────────────────────────────────────────────────────
# Marketplace domain: Genre Service Tests
# ─────────────────────────────────────────────────────────────

class TestGenreService:

    def test_add_genre_success(self):
        from app.schema.marketplace import GenreCreate
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        data = GenreCreate(name="City Pop")

        result = GenreService.add_genre(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_get_genres_found(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = GenreService.get_genres(db)
        assert len(result) == 1

    def test_get_genres_empty(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().all.return_value = []

        result = GenreService.get_genres(db)
        assert result is False

    def test_delete_genre_success(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_genre = MagicMock()
        db.get.return_value = mock_genre

        result = GenreService.delete_genre(db, DEFAULT_ID)
        db.delete.assert_called_once_with(mock_genre)
        db.commit.assert_called_once()
        assert result is True

    def test_delete_genre_not_found(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.get.return_value = None

        result = GenreService.delete_genre(db, MISSING_ID)
        assert result is False

    def test_assign_genre_success(self):
        from app.db.models.marketplace import AlbumDetail, AlbumGenre, Genre
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({
            AlbumDetail: mock_album, Idol: mock_idol, Genre: MagicMock(), AlbumGenre: None,
        })
        current_user = make_mock_user(role="admin")
        data = AlbumGenreAssign(product_id=DEFAULT_ID, genre_id=DEFAULT_ID)

        result = GenreService.assign_genre(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_assign_genre_album_not_found(self):
        from app.db.models.marketplace import AlbumDetail
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({AlbumDetail: None})
        current_user = make_mock_user(role="admin")
        data = AlbumGenreAssign(product_id=MISSING_ID, genre_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            GenreService.assign_genre(db, data, current_user)

    def test_assign_genre_genre_not_found(self):
        from app.db.models.marketplace import AlbumDetail, Genre
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol, Genre: None})
        current_user = make_mock_user(role="admin")
        data = AlbumGenreAssign(product_id=DEFAULT_ID, genre_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            GenreService.assign_genre(db, data, current_user)

    def test_assign_genre_forbidden(self):
        from app.db.models.marketplace import AlbumDetail, Genre
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol, Genre: MagicMock()})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = AlbumGenreAssign(product_id=DEFAULT_ID, genre_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GenreService.assign_genre(db, data, current_user)

    def test_assign_genre_conflict(self):
        from app.db.models.marketplace import AlbumDetail, AlbumGenre, Genre
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({
            AlbumDetail: mock_album, Idol: mock_idol, Genre: MagicMock(), AlbumGenre: MagicMock(),
        })
        current_user = make_mock_user(role="admin")
        data = AlbumGenreAssign(product_id=DEFAULT_ID, genre_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            GenreService.assign_genre(db, data, current_user)

    def test_get_album_genres_found(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().filter().all.return_value = [MagicMock()]

        result = GenreService.get_album_genres(db, DEFAULT_ID)
        assert len(result) == 1

    def test_get_album_genres_empty(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = GenreService.get_album_genres(db, DEFAULT_ID)
        assert result is False

    def test_get_all_album_genres_found(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().all.return_value = [MagicMock(), MagicMock()]

        result = GenreService.get_all_album_genres(db)
        assert len(result) == 2

    def test_get_all_album_genres_empty(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().all.return_value = []

        result = GenreService.get_all_album_genres(db)
        assert result is False

    def test_remove_genre_success(self):
        from app.db.models.marketplace import AlbumDetail, AlbumGenre
        from app.db.models.talent import Idol
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        link = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({
            AlbumGenre: link, AlbumDetail: mock_album, Idol: mock_idol,
        })
        current_user = make_mock_user(role="admin")

        result = GenreService.remove_genre(db, DEFAULT_ID, DEFAULT_ID, current_user)
        assert result is link
        db.delete.assert_called_once_with(link)

    def test_remove_genre_not_found(self):
        from app.db.models.marketplace import AlbumGenre
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({AlbumGenre: None})
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            GenreService.remove_genre(db, MISSING_ID, MISSING_ID, current_user)

    def test_remove_genre_forbidden(self):
        from app.db.models.marketplace import AlbumDetail, AlbumGenre
        from app.db.models.talent import Idol
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        link = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({
            AlbumGenre: link, AlbumDetail: mock_album, Idol: mock_idol,
        })
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GenreService.remove_genre(db, DEFAULT_ID, DEFAULT_ID, current_user)
