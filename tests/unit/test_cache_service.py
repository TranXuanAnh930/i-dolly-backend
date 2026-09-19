import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import fake_redis

# ───────────────────────────────────────────────────────────────
# CacheService is backed by tests/conftest.py's session-wide fake_redis
# (patched in for app.cache.redis_client.redis_client), not a per-test
# MagicMock — these tests exercise the real get/setex/delete/keys calls
# against an in-memory Redis, so a cache-hit genuinely skips the wrapped
# *Service call and a delete genuinely removes the key. Flushed before each
# test since fake_redis is shared for the whole session (same reasoning as
# test_rate_limit.py's own autouse fixture, just a full flush here since
# cache_service.py owns the entire keyspace other than "rate:*").
# ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_cache():
    fake_redis.flushdb()
    yield

DEFAULT_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
NOW = datetime.now(timezone.utc)

# ───────────────────────────────────────────────────────────────
# Helpers — minimal but real (not MagicMock) schema instances, since the
# cache path round-trips them through msgpack, which can't serialize a mock.
# ───────────────────────────────────────────────────────────────

def make_product_card(id=DEFAULT_ID, name="Album"):
    from app.schema.marketplace import ProductCard
    return ProductCard(id=id, name=name, price=10.0, description="d", quantity=5, category="Merch")

def make_venue_read(id=DEFAULT_ID):
    from app.schema.events import VenueRead
    return VenueRead(
        id=id, name="Arena", address="1 Main St", city="Tokyo", country="Japan",
        total_capacity=1000, contact_info=None, size="medium", created_at=NOW,
    )

def make_concert_read(id=DEFAULT_ID, venue_id=DEFAULT_ID):
    from app.schema.events import ConcertRead
    return ConcertRead(
        id=id, company_id=DEFAULT_ID, venue_id=venue_id, title="Concert", description=None,
        capacity=500, event_datetime=NOW, doors_open_at=None, status="scheduled",
        created_at=NOW, updated_at=NOW,
    )

def make_idol_with_positions(id=DEFAULT_ID):
    from app.schema.talent import IdolWithPositions
    return IdolWithPositions(
        id=id, company_id=DEFAULT_ID, name="Idol", is_active=True, created_at=NOW, updated_at=NOW,
    )

def make_group_read(id=DEFAULT_ID):
    from app.schema.talent import GroupRead
    return GroupRead(id=id, company_id=DEFAULT_ID, name="Group", is_active=True, created_at=NOW, updated_at=NOW)

def make_product_read(id=DEFAULT_ID):
    from app.schema.marketplace import ProductRead
    return ProductRead(id=id, name="Product", price=10.0, description="d", quantity=5, category="Merch")

# ───────────────────────────────────────────────────────────────
# products:list / products:store_page (get_cached_products, get_cached_store_page,
# delete_cached_products) — the two keys sharing one delete
# ───────────────────────────────────────────────────────────────

class TestProductsCache:

    def test_get_cached_products_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.services.marketplace.product_service import ProductService

        mock_product = MagicMock(id=DEFAULT_ID, price=999.0, description="d", quantity=1, image_url=None)
        mock_product.name = "Phone"
        mock_product.category.name = "Electronics"
        db = MagicMock()

        with patch.object(ProductService, "list_of_products", return_value=[mock_product]) as mocked:
            first = CacheService.get_cached_products(db)
            assert first[0]["name"] == "Phone"
            mocked.assert_called_once()

            second = CacheService.get_cached_products(db)
            assert second == first
            mocked.assert_called_once()  # still once — the second call hit the cache

    def test_get_cached_products_empty(self):
        from app.cache.cache_service import CacheService
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        with patch.object(ProductService, "list_of_products", return_value=False):
            result = CacheService.get_cached_products(db)
        assert result == []
        assert fake_redis.get("products:list") is None  # empty result never cached

    def test_get_cached_store_page_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.schema.marketplace import StorePageRead
        from app.services.marketplace.product_service import ProductService

        page = StorePageRead(products=[make_product_card()], groups=[])
        db = MagicMock()

        with patch.object(ProductService, "get_store_page", return_value=page) as mocked:
            first = CacheService.get_cached_store_page(db)
            assert first.products[0].id == DEFAULT_ID
            mocked.assert_called_once()

            second = CacheService.get_cached_store_page(db)
            assert second.products[0].id == DEFAULT_ID
            mocked.assert_called_once()

    def test_get_cached_store_page_not_found(self):
        from app.cache.cache_service import CacheService
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        with patch.object(ProductService, "get_store_page", return_value=False):
            result = CacheService.get_cached_store_page(db)
        assert result is False

    def test_delete_cached_products_clears_both_keys(self):
        from app.cache.cache_service import CacheService

        fake_redis.set("products:list", b"x")
        fake_redis.set("products:store_page", b"x")

        CacheService.delete_cached_products()

        assert fake_redis.get("products:list") is None
        assert fake_redis.get("products:store_page") is None

# ───────────────────────────────────────────────────────────────
# products:<id>:detail — per-id keyed, wildcard-cleared
# ───────────────────────────────────────────────────────────────

class TestProductDetailCache:

    def test_get_cached_product_detail_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.schema.marketplace import ProductDetailRead
        from app.services.marketplace.product_service import ProductService

        detail = ProductDetailRead(product=make_product_card(), recommendations=[])
        db = MagicMock()

        with patch.object(ProductService, "get_product_detail", return_value=detail) as mocked:
            first = CacheService.get_cached_product_detail(db, DEFAULT_ID)
            assert first.product.id == DEFAULT_ID
            mocked.assert_called_once()

            second = CacheService.get_cached_product_detail(db, DEFAULT_ID)
            assert second.product.id == DEFAULT_ID
            mocked.assert_called_once()

    def test_get_cached_product_detail_not_found(self):
        from app.cache.cache_service import CacheService
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        with patch.object(ProductService, "get_product_detail", return_value=False):
            result = CacheService.get_cached_product_detail(db, OTHER_ID)
        assert result is False
        assert fake_redis.get(f"products:{OTHER_ID}:detail") is None

    def test_delete_cached_product_details_clears_every_id(self):
        from app.cache.cache_service import CacheService

        fake_redis.set(f"products:{DEFAULT_ID}:detail", b"x")
        fake_redis.set(f"products:{OTHER_ID}:detail", b"x")

        CacheService.delete_cached_product_details()

        assert fake_redis.get(f"products:{DEFAULT_ID}:detail") is None
        assert fake_redis.get(f"products:{OTHER_ID}:detail") is None

# ───────────────────────────────────────────────────────────────
# concerts:<id>:detail — per-id keyed, precisely (not wildcard) cleared
# ───────────────────────────────────────────────────────────────

class TestConcertDetailCache:

    def test_get_cached_concert_detail_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.schema.events import ConcertDetailRead
        from app.services.events.concert_service import ConcertService

        detail = ConcertDetailRead(
            concert=make_concert_read(), venue=make_venue_read(), ticket_types=[], lineup=[],
            performing_groups=[], lottery_campaigns=[], direct_sale_campaigns=[],
        )
        db = MagicMock()

        with patch.object(ConcertService, "get_concert_detail_public", return_value=detail) as mocked:
            first = CacheService.get_cached_concert_detail(db, DEFAULT_ID)
            assert first.concert.id == DEFAULT_ID
            # Personalized fields default to False/empty on the cached bundle —
            # CacheService never computes or caches them (see cache_service.py's
            # own comment on this method).
            assert first.has_ticket is False
            assert first.my_lottery_preferences == []
            mocked.assert_called_once()

            second = CacheService.get_cached_concert_detail(db, DEFAULT_ID)
            assert second.concert.id == DEFAULT_ID
            mocked.assert_called_once()

    def test_get_cached_concert_detail_not_found(self):
        from app.cache.cache_service import CacheService
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        with patch.object(ConcertService, "get_concert_detail_public", return_value=False):
            result = CacheService.get_cached_concert_detail(db, OTHER_ID)
        assert result is False

    def test_delete_cached_concert_detail_is_precise_not_wildcard(self):
        from app.cache.cache_service import CacheService

        fake_redis.set(f"concerts:{DEFAULT_ID}:detail", b"x")
        fake_redis.set(f"concerts:{OTHER_ID}:detail", b"x")

        CacheService.delete_cached_concert_detail(DEFAULT_ID)

        assert fake_redis.get(f"concerts:{DEFAULT_ID}:detail") is None
        assert fake_redis.get(f"concerts:{OTHER_ID}:detail") is not None  # untouched

# ───────────────────────────────────────────────────────────────
# idols:detail:<id> / groups:detail:<id> — per-id keyed, wildcard-cleared
# together (idol/group detail pages embed each other's data)
# ───────────────────────────────────────────────────────────────

class TestIdolAndGroupDetailCache:

    def test_get_cached_idol_detail_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.schema.talent import IdolDetailRead
        from app.services.talent.idol_service import IdolService

        detail = IdolDetailRead(idol=make_idol_with_positions(), group=None, siblings=[])
        db = MagicMock()

        with patch.object(IdolService, "get_idol_detail", return_value=detail) as mocked:
            first = CacheService.get_cached_idol_detail(db, DEFAULT_ID)
            assert first.idol.id == DEFAULT_ID
            mocked.assert_called_once()

            CacheService.get_cached_idol_detail(db, DEFAULT_ID)
            mocked.assert_called_once()

    def test_get_cached_idol_detail_not_found(self):
        from app.cache.cache_service import CacheService
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        with patch.object(IdolService, "get_idol_detail", return_value=False):
            result = CacheService.get_cached_idol_detail(db, OTHER_ID)
        assert result is False

    def test_get_cached_group_detail_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.schema.talent import GroupDetailRead
        from app.services.talent.group_service import GroupService

        detail = GroupDetailRead(group=make_group_read(), members=[], events=[], products=[])
        db = MagicMock()

        with patch.object(GroupService, "get_group_detail", return_value=detail) as mocked:
            first = CacheService.get_cached_group_detail(db, DEFAULT_ID)
            assert first.group.id == DEFAULT_ID
            mocked.assert_called_once()

            CacheService.get_cached_group_detail(db, DEFAULT_ID)
            mocked.assert_called_once()

    def test_get_cached_group_detail_not_found(self):
        from app.cache.cache_service import CacheService
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        with patch.object(GroupService, "get_group_detail", return_value=False):
            result = CacheService.get_cached_group_detail(db, OTHER_ID)
        assert result is False

    def test_delete_cached_idol_details_clears_every_id(self):
        from app.cache.cache_service import CacheService

        fake_redis.set(f"idols:detail:{DEFAULT_ID}", b"x")
        fake_redis.set(f"idols:detail:{OTHER_ID}", b"x")

        CacheService.delete_cached_idol_details()

        assert fake_redis.get(f"idols:detail:{DEFAULT_ID}") is None
        assert fake_redis.get(f"idols:detail:{OTHER_ID}") is None

    def test_delete_cached_group_details_clears_every_id(self):
        from app.cache.cache_service import CacheService

        fake_redis.set(f"groups:detail:{DEFAULT_ID}", b"x")
        fake_redis.set(f"groups:detail:{OTHER_ID}", b"x")

        CacheService.delete_cached_group_details()

        assert fake_redis.get(f"groups:detail:{DEFAULT_ID}") is None
        assert fake_redis.get(f"groups:detail:{OTHER_ID}") is None

# ───────────────────────────────────────────────────────────────
# Static lookup-table caches (venues, idol colors, management companies) —
# same shape as products:list: hand-rolled dict payload, Literal[False] on
# an empty result.
# ───────────────────────────────────────────────────────────────

class TestLookupTableCaches:

    def test_get_cached_venues_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        with patch.object(VenueService, "get_venues", return_value=[make_venue_read()]) as mocked:
            first = CacheService.get_cached_venues(db)
            assert first[0]["id"] == str(DEFAULT_ID)
            mocked.assert_called_once()

            CacheService.get_cached_venues(db)
            mocked.assert_called_once()

    def test_get_cached_venues_empty(self):
        from app.cache.cache_service import CacheService
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        with patch.object(VenueService, "get_venues", return_value=False):
            result = CacheService.get_cached_venues(db)
        assert result is False

    def test_delete_cached_venues(self):
        from app.cache.cache_service import CacheService

        fake_redis.set("venues:all", b"x")
        CacheService.delete_cached_venues()
        assert fake_redis.get("venues:all") is None

    def test_get_cached_idol_colors_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.services.talent.idol_color_service import IdolColorService

        mock_color = MagicMock(id=DEFAULT_ID, hex_code="#FF0000")
        mock_color.name = "Crimson"
        db = MagicMock()
        with patch.object(IdolColorService, "get_idol_colors", return_value=[mock_color]) as mocked:
            first = CacheService.get_cached_idol_colors(db)
            assert first[0]["name"] == "Crimson"
            mocked.assert_called_once()

            CacheService.get_cached_idol_colors(db)
            mocked.assert_called_once()

    def test_delete_cached_idol_colors(self):
        from app.cache.cache_service import CacheService

        fake_redis.set("idol_colors:all", b"x")
        CacheService.delete_cached_idol_colors()
        assert fake_redis.get("idol_colors:all") is None

    def test_get_cached_management_companies_miss_then_hit(self):
        from app.cache.cache_service import CacheService
        from app.services.talent.management_company_service import ManagementCompanyService

        mock_company = MagicMock(id=DEFAULT_ID, description=None, contact_email=None)
        mock_company.name = "Nova Entertainment"
        db = MagicMock()
        with patch.object(ManagementCompanyService, "get_companies", return_value=[mock_company]) as mocked:
            first = CacheService.get_cached_management_companies(db)
            assert first[0]["name"] == "Nova Entertainment"
            mocked.assert_called_once()

            CacheService.get_cached_management_companies(db)
            mocked.assert_called_once()

    def test_delete_cached_management_companies(self):
        from app.cache.cache_service import CacheService

        fake_redis.set("management_companies:all", b"x")
        CacheService.delete_cached_management_companies()
        assert fake_redis.get("management_companies:all") is None

# ───────────────────────────────────────────────────────────────
# Shared/manager page caches — never 404, so no Literal[False] branch.
# ───────────────────────────────────────────────────────────────

class TestPageCaches:

    def test_get_cached_events_page(self):
        from app.cache.cache_service import CacheService
        from app.schema.events import EventsPageRead
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        with patch.object(ConcertService, "get_events_page", return_value=EventsPageRead(concerts=[])) as mocked:
            CacheService.get_cached_events_page(db)
            CacheService.get_cached_events_page(db)
            mocked.assert_called_once()

        fake_redis.set("concerts:events_page", b"x")
        CacheService.delete_cached_events_page()
        assert fake_redis.get("concerts:events_page") is None

    def test_get_cached_members_page(self):
        from app.cache.cache_service import CacheService
        from app.schema.talent import MembersPageRead
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        with patch.object(IdolService, "get_members_page", return_value=MembersPageRead(idols=[], groups=[])) as mocked:
            CacheService.get_cached_members_page(db)
            CacheService.get_cached_members_page(db)
            mocked.assert_called_once()

        fake_redis.set("idols:members_page", b"x")
        CacheService.delete_cached_members_page()
        assert fake_redis.get("idols:members_page") is None

    def test_get_cached_groups_page(self):
        from app.cache.cache_service import CacheService
        from app.schema.talent import GroupsPageRead
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        with patch.object(GroupService, "get_groups_page", return_value=GroupsPageRead(groups=[])) as mocked:
            CacheService.get_cached_groups_page(db)
            CacheService.get_cached_groups_page(db)
            mocked.assert_called_once()

        fake_redis.set("groups:groups_page", b"x")
        CacheService.delete_cached_groups_page()
        assert fake_redis.get("groups:groups_page") is None

    def test_get_cached_manager_idols_page_never_404s(self):
        from app.cache.cache_service import CacheService
        from app.schema.talent import ManagerIdolsPageRead
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        page = ManagerIdolsPageRead(idols=[], groups=[])
        with patch.object(IdolService, "get_manager_idols_page", return_value=page) as mocked:
            result = CacheService.get_cached_manager_idols_page(db)
            assert result.idols == []
            CacheService.get_cached_manager_idols_page(db)
            mocked.assert_called_once()

        fake_redis.set("idols:manager_idols_page", b"x")
        CacheService.delete_cached_manager_idols_page()
        assert fake_redis.get("idols:manager_idols_page") is None

    def test_get_cached_manager_idol_form_page(self):
        from app.cache.cache_service import CacheService
        from app.schema.talent import ManagerIdolFormPageRead
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        page = ManagerIdolFormPageRead(idols=[], groups=[], colors=[])
        with patch.object(IdolService, "get_manager_idol_form_page", return_value=page) as mocked:
            CacheService.get_cached_manager_idol_form_page(db)
            CacheService.get_cached_manager_idol_form_page(db)
            mocked.assert_called_once()

        fake_redis.set("idols:manager_idol_form_page", b"x")
        CacheService.delete_cached_manager_idol_form_page()
        assert fake_redis.get("idols:manager_idol_form_page") is None

    def test_get_cached_manager_groups_page(self):
        from app.cache.cache_service import CacheService
        from app.schema.talent import ManagerGroupsPageRead
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        page = ManagerGroupsPageRead(groups=[])
        with patch.object(GroupService, "get_manager_groups_page", return_value=page) as mocked:
            CacheService.get_cached_manager_groups_page(db)
            CacheService.get_cached_manager_groups_page(db)
            mocked.assert_called_once()

        fake_redis.set("groups:manager_groups_page", b"x")
        CacheService.delete_cached_manager_groups_page()
        assert fake_redis.get("groups:manager_groups_page") is None

    def test_get_cached_manager_events_page(self):
        from app.cache.cache_service import CacheService
        from app.schema.events import ManagerEventsPageRead
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        page = ManagerEventsPageRead(concerts=[], venues=[])
        with patch.object(ConcertService, "get_manager_events_page", return_value=page) as mocked:
            CacheService.get_cached_manager_events_page(db)
            CacheService.get_cached_manager_events_page(db)
            mocked.assert_called_once()

        fake_redis.set("concerts:manager_events_page", b"x")
        CacheService.delete_cached_manager_events_page()
        assert fake_redis.get("concerts:manager_events_page") is None

# ───────────────────────────────────────────────────────────────
# products:manager_products_page:<company_id|"all"> — the one cache keyed
# per company_id, so two companies' managers must never share an entry.
# ───────────────────────────────────────────────────────────────

class TestManagerProductsPageCache:

    def test_different_company_ids_get_separate_cache_entries(self):
        from app.cache.cache_service import CacheService
        from app.schema.marketplace import ManagerProductsPageRead
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        page_a = ManagerProductsPageRead(products=[make_product_read(id=DEFAULT_ID)])
        page_b = ManagerProductsPageRead(products=[make_product_read(id=OTHER_ID)])

        def fake_get(db, company_id):
            return page_a if company_id == DEFAULT_ID else page_b

        with patch.object(ProductService, "get_manager_products_page", side_effect=fake_get) as mocked:
            result_a = CacheService.get_cached_manager_products_page(db, DEFAULT_ID)
            result_b = CacheService.get_cached_manager_products_page(db, OTHER_ID)
            assert result_a.products[0].id == DEFAULT_ID
            assert result_b.products[0].id == OTHER_ID
            assert mocked.call_count == 2

            # Re-requesting either company's page now hits its own cache entry —
            # no cross-company leakage, and no extra service call.
            CacheService.get_cached_manager_products_page(db, DEFAULT_ID)
            CacheService.get_cached_manager_products_page(db, OTHER_ID)
            assert mocked.call_count == 2

    def test_none_company_id_maps_to_all(self):
        from app.cache.cache_service import CacheService
        from app.schema.marketplace import ManagerProductsPageRead
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        page = ManagerProductsPageRead(products=[])
        with patch.object(ProductService, "get_manager_products_page", return_value=page):
            CacheService.get_cached_manager_products_page(db, None)

        assert fake_redis.get("products:manager_products_page:all") is not None

    def test_delete_cached_manager_products_pages_clears_both_patterns(self):
        from app.cache.cache_service import CacheService

        fake_redis.set(f"products:manager_products_page:{DEFAULT_ID}", b"x")
        fake_redis.set("products:manager_products_page:all", b"x")
        fake_redis.set(f"products:manager_product_form_page:{DEFAULT_ID}", b"x")

        CacheService.delete_cached_manager_products_pages()

        assert fake_redis.get(f"products:manager_products_page:{DEFAULT_ID}") is None
        assert fake_redis.get("products:manager_products_page:all") is None
        assert fake_redis.get(f"products:manager_product_form_page:{DEFAULT_ID}") is None

    def test_get_cached_manager_product_form_page(self):
        from app.cache.cache_service import CacheService
        from app.schema.marketplace import ManagerProductFormPageRead
        from app.services.marketplace.product_service import ProductService

        db = MagicMock()
        page = ManagerProductFormPageRead(products=[], categories=[], idols=[], groups=[], colors=[])
        with patch.object(ProductService, "get_manager_product_form_page", return_value=page) as mocked:
            CacheService.get_cached_manager_product_form_page(db, DEFAULT_ID)
            CacheService.get_cached_manager_product_form_page(db, DEFAULT_ID)
            mocked.assert_called_once()
