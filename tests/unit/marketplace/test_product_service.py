import uuid
from unittest.mock import MagicMock

import pytest

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


# ───────────────────────────────────────────────────────────────
# Product Service Tests
# ───────────────────────────────────────────────────────────────

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
        assert result is None

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
        assert result is None

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
        assert result is mock_prod

    def test_update_product_not_found(self):
        from app.exception.common import NotFoundError
        from app.schema.marketplace import ProductCreate
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.get.return_value = None
        admin = make_mock_user(role="admin")
        update_data = ProductCreate(name="Updated", price=100.0, description="Updated", quantity=5, category_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            ProductService.update_product(db, MISSING_ID, update_data, admin)

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
        from app.exception.common import NotFoundError
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.get.return_value = None
        admin = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            ProductService.delete_product(db, MISSING_ID, admin)

    def test_pagination_process(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        mock_products = [make_mock_product()]
        db.query().offset().limit().all.return_value = mock_products

        result = ProductService.pagination_process(db, page=1, limit=10)
        assert len(result) == 1


def make_mock_idol(id=DEFAULT_ID, name="Idol", company_id=DEFAULT_ID, is_active=True):
    idol = MagicMock()
    idol.id = id
    idol.name = name
    idol.company_id = company_id
    idol.is_active = is_active
    idol.color = None
    return idol

def make_mock_album_detail(product_id, idol_id=None, group_id=None):
    album = MagicMock()
    album.product_id = product_id
    album.idol_id = idol_id
    album.group_id = group_id
    album.release_date = None
    album.track_count = None
    album.cover_image_url = None
    return album

def make_products_query_db(products, albums=None, merch=None, album_genres=None, idols=None, groups=None):
    """Mocks the chain of db.query(Model) calls _build_product_cards makes —
    one call per model class, each with its own distinct chain shape."""
    from app.db.models.marketplace import AlbumDetail, AlbumGenre, MerchDetail, Product
    from app.db.models.talent import Group, Idol

    db = MagicMock()

    def query_side_effect(model, *cols):
        q = MagicMock()
        if model is Product:
            q.options.return_value.filter.return_value.first.return_value = (
                products[0] if len(products) == 1 else None
            )
            q.options.return_value.all.return_value = products
        elif model is AlbumDetail:
            q.filter.return_value.all.return_value = albums or []
        elif model is MerchDetail:
            q.filter.return_value.all.return_value = merch or []
        elif model is AlbumGenre:
            q.options.return_value.filter.return_value.all.return_value = album_genres or []
        elif model is Idol:
            q.options.return_value.all.return_value = idols or []
        elif model is Group:
            q.all.return_value = groups or []
        return q

    db.query.side_effect = query_side_effect
    return db

# ───────────────────────────────────────────────────────────────
# Page-shaped reads (get_store_page, get_product_detail) — exercise
# _build_product_cards' artist/recommendation resolution.
# ───────────────────────────────────────────────────────────────

class TestProductPages:

    def test_get_store_page_empty(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.query().options().all.return_value = []

        result = ProductService.get_store_page(db)
        assert result is None

    def test_get_store_page_resolves_idol_artist_from_album_detail(self):
        from app.services.marketplace.product_service import ProductService

        product = make_mock_product(id=DEFAULT_ID, name="Debut Album")
        idol = make_mock_idol(id=OTHER_ID, name="Idol")
        album = make_mock_album_detail(product_id=DEFAULT_ID, idol_id=OTHER_ID)
        db = make_products_query_db([product], albums=[album], idols=[idol])

        result = ProductService.get_store_page(db)

        assert len(result.products) == 1
        card = result.products[0]
        assert card.artist.type == "idol"
        assert card.artist.id == OTHER_ID
        assert card.album is not None

    def test_get_product_detail_not_found(self):
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.query().options().filter().first.return_value = None

        result = ProductService.get_product_detail(db, MISSING_ID)
        assert result is None

    def test_get_product_detail_recommends_same_artist_not_unrelated(self):
        from app.services.marketplace.product_service import ProductService

        target_id, same_artist_id, unrelated_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        idol_a, idol_b = uuid.uuid4(), uuid.uuid4()

        target = make_mock_product(id=target_id, name="Target Album")
        same_artist = make_mock_product(id=same_artist_id, name="Same Artist Album")
        unrelated = make_mock_product(id=unrelated_id, name="Unrelated Album")

        albums = [
            make_mock_album_detail(product_id=target_id, idol_id=idol_a),
            make_mock_album_detail(product_id=same_artist_id, idol_id=idol_a),
            make_mock_album_detail(product_id=unrelated_id, idol_id=idol_b),
        ]
        idols = [make_mock_idol(id=idol_a, name="Idol A"), make_mock_idol(id=idol_b, name="Idol B")]

        db = MagicMock()
        from app.db.models.marketplace import AlbumDetail, AlbumGenre, MerchDetail, Product
        from app.db.models.talent import Group, Idol

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model is Product:
                q.options.return_value.filter.return_value.first.return_value = target
                q.options.return_value.all.return_value = [target, same_artist, unrelated]
            elif model is AlbumDetail:
                q.filter.return_value.all.return_value = albums
            elif model is MerchDetail:
                q.filter.return_value.all.return_value = []
            elif model is AlbumGenre:
                q.options.return_value.filter.return_value.all.return_value = []
            elif model is Idol:
                q.options.return_value.all.return_value = idols
            elif model is Group:
                q.all.return_value = []
            return q

        db.query.side_effect = query_side_effect

        result = ProductService.get_product_detail(db, target_id)

        assert result.product.id == target_id
        recommended_ids = {r.id for r in result.recommendations}
        assert same_artist_id in recommended_ids
        assert unrelated_id not in recommended_ids
        assert target_id not in recommended_ids  # never recommends itself

# ───────────────────────────────────────────────────────────────
# get_product_sales_page
# ───────────────────────────────────────────────────────────────

class TestProductSalesPage:

    def test_not_found(self):
        from app.exception.common import NotFoundError
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        db.get.return_value = None
        admin = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            ProductService.get_product_sales_page(db, MISSING_ID, admin)

    def test_manager_wrong_company_forbidden(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Idol
        from app.exception.common import ForbiddenError
        from app.services.marketplace.product_service import ProductService

        product = make_mock_product()
        album = make_mock_album_detail(product_id=DEFAULT_ID, idol_id=OTHER_ID)
        idol = make_mock_idol(id=OTHER_ID, company_id=OTHER_ID)

        db = MagicMock()
        db.get.side_effect = lambda model, ident=None: {
            Product: product, AlbumDetail: album, Idol: idol,
        }.get(model)
        manager = make_mock_user(role="manager")
        manager.company_id = DEFAULT_ID

        with pytest.raises(ForbiddenError):
            ProductService.get_product_sales_page(db, DEFAULT_ID, manager)

    def test_success_returns_paginated_sales(self):
        from app.db.models.marketplace import AlbumDetail
        from app.services.marketplace.product_service import ProductService

        product = make_mock_product()
        db = MagicMock()
        db.get.side_effect = lambda model, ident=None: product if model is not AlbumDetail else None

        sale_item = MagicMock()
        sale_item.order_id = uuid.uuid4()
        sale_item.quantity = 2
        sale_item.price = 50.0
        sale_item.order.status = "confirmed"
        sale_item.order.created_at = MagicMock()

        db.query().join().filter().options().order_by().offset().limit().all.return_value = [sale_item]
        admin = make_mock_user(role="admin")

        result = ProductService.get_product_sales_page(db, DEFAULT_ID, admin, page=1, limit=10)

        assert result.count == 1
        assert result.data[0].line_total == 100.0
