import uuid
from typing import Any

import msgpack
from sqlalchemy.orm import Session

from app.cache.invalidation import (
    EVENTS_PAGE_KEY,
    GROUPS_PAGE_KEY,
    IDOL_COLORS_KEY,
    MANAGEMENT_COMPANIES_KEY,
    MANAGER_EVENTS_PAGE_KEY,
    MANAGER_GROUPS_PAGE_KEY,
    MANAGER_IDOL_FORM_PAGE_KEY,
    MANAGER_IDOLS_PAGE_KEY,
    MEMBERS_PAGE_KEY,
    PRODUCTS_LIST_KEY,
    STORE_PAGE_KEY,
    TTL_SECONDS,
    VENUES_KEY,
    CacheInvalidation,
    concert_detail_key,
    group_detail_key,
    idol_detail_key,
    manager_product_form_page_key,
    manager_products_page_key,
    product_detail_key,
)
from app.cache.redis_client import redis_client
from app.schema.events import ConcertDetailRead, EventsPageRead, ManagerEventsPageRead, VenueRead
from app.schema.marketplace import (
    ManagerProductFormPageRead,
    ManagerProductsPageRead,
    ProductDetailRead,
    ProductRead,
    StorePageRead,
)
from app.schema.talent import (
    GroupDetailRead,
    GroupsPageRead,
    IdolColorRead,
    IdolDetailRead,
    ManagementCompanyRead,
    ManagerGroupsPageRead,
    ManagerIdolFormPageRead,
    ManagerIdolsPageRead,
    MembersPageRead,
)
from app.services.events.concert_service import ConcertService
from app.services.events.venue_service import VenueService
from app.services.marketplace.product_service import ProductService
from app.services.talent.group_service import GroupService
from app.services.talent.idol_color_service import IdolColorService
from app.services.talent.idol_service import IdolService
from app.services.talent.management_company_service import ManagementCompanyService


# Redis cache-aside reads: return the cached value, or build it via a service and cache it.
# Invalidation methods are inherited from CacheInvalidation.
class CacheService(CacheInvalidation):

    @staticmethod
    def get_cached_products(db: Session) -> list[dict[str, Any]]:
        cache_key = PRODUCTS_LIST_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return msgpack.unpackb(cached, raw=False)
        products = ProductService.list_of_products(db)

        if not products:
            return []

        # ProductRead has no from_attributes, so build a dict (resolving the category name) and
        # validate it through the schema.
        payload = [
            ProductRead.model_validate({
                "id": p.id,
                "name": p.name,
                "price": p.price,
                "description": p.description,
                "quantity": p.quantity,
                "image_url": p.image_url,
                "category": p.category.name if p.category else None,
            }).model_dump(mode="json")
            for p in products
        ]
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(payload))
        return payload

    @staticmethod
    def get_cached_store_page(db: Session) -> StorePageRead | None:
        cache_key = STORE_PAGE_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return StorePageRead.model_validate(msgpack.unpackb(cached, raw=False))

        # Stored as model_dump(mode="json") so msgpack can serialize it.
        result = ProductService.get_store_page(db)
        if not result:
            return None

        payload = result.model_dump(mode="json")
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(payload))
        return result

    @staticmethod
    def get_cached_product_detail(db: Session, id: uuid.UUID) -> ProductDetailRead | None:
        cache_key = product_detail_key(id)
        cached = redis_client.get(cache_key)
        if cached:
            return ProductDetailRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ProductService.get_product_detail(db, id)
        if not result:
            return None
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_events_page(db: Session) -> EventsPageRead | None:
        cache_key = EVENTS_PAGE_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return EventsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ConcertService.get_events_page(db)
        if not result:
            return None
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    # Caches only the viewer-independent concert detail; per-viewer fields are never stored.
    @staticmethod
    def get_cached_concert_detail(db: Session, id: uuid.UUID) -> ConcertDetailRead | None:
        cache_key = concert_detail_key(id)
        cached = redis_client.get(cache_key)
        if cached:
            return ConcertDetailRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ConcertService.get_concert_detail_public(db, id)
        if not result:
            return None
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_members_page(db: Session) -> MembersPageRead | None:
        cache_key = MEMBERS_PAGE_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return MembersPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = IdolService.get_members_page(db)
        if not result:
            return None
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_idol_detail(db: Session, id: uuid.UUID) -> IdolDetailRead | None:
        cache_key = idol_detail_key(id)
        cached = redis_client.get(cache_key)
        if cached:
            return IdolDetailRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = IdolService.get_idol_detail(db, id)
        if not result:
            return None
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_groups_page(db: Session) -> GroupsPageRead | None:
        cache_key = GROUPS_PAGE_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return GroupsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = GroupService.get_groups_page(db)
        if not result:
            return None
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_group_detail(db: Session, id: uuid.UUID) -> GroupDetailRead | None:
        cache_key = group_detail_key(id)
        cached = redis_client.get(cache_key)
        if cached:
            return GroupDetailRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = GroupService.get_group_detail(db, id)
        if not result:
            return None
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    # Venues and idol colors: small lookup tables, cached with the same TTL + invalidate-on-write.

    @staticmethod
    def get_cached_venues(db: Session) -> list[dict[str, Any]] | None:
        cache_key = VENUES_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return msgpack.unpackb(cached, raw=False)

        venues = VenueService.get_venues(db)
        if not venues:
            return None
        payload = [VenueRead.model_validate(v).model_dump(mode="json") for v in venues]
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(payload))
        return payload

    @staticmethod
    def get_cached_idol_colors(db: Session) -> list[dict[str, Any]] | None:
        cache_key = IDOL_COLORS_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return msgpack.unpackb(cached, raw=False)

        colors = IdolColorService.get_idol_colors(db)
        if not colors:
            return None
        payload = [IdolColorRead.model_validate(c).model_dump(mode="json") for c in colors]
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(payload))
        return payload

    # --- Manager/admin settings pages. These always return a page object (possibly empty), never None.

    @staticmethod
    def get_cached_manager_idols_page(db: Session) -> ManagerIdolsPageRead:
        cache_key = MANAGER_IDOLS_PAGE_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerIdolsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = IdolService.get_manager_idols_page(db)
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_manager_idol_form_page(db: Session) -> ManagerIdolFormPageRead:
        cache_key = MANAGER_IDOL_FORM_PAGE_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerIdolFormPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = IdolService.get_manager_idol_form_page(db)
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_manager_groups_page(db: Session) -> ManagerGroupsPageRead:
        cache_key = MANAGER_GROUPS_PAGE_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerGroupsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = GroupService.get_manager_groups_page(db)
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_manager_events_page(db: Session) -> ManagerEventsPageRead:
        cache_key = MANAGER_EVENTS_PAGE_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerEventsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ConcertService.get_manager_events_page(db)
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    # Manager product pages are cached per company_id (None = admin, all companies). Product has no
    # company_id column, so a write clears every company's entry. keys() is an O(N) scan; use SCAN at
    # larger key counts.

    @staticmethod
    def get_cached_manager_products_page(db: Session, company_id: uuid.UUID | None) -> ManagerProductsPageRead:
        cache_key = manager_products_page_key(company_id)
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerProductsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ProductService.get_manager_products_page(db, company_id)
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_manager_product_form_page(db: Session, company_id: uuid.UUID | None) -> ManagerProductFormPageRead:
        cache_key = manager_product_form_page_key(company_id)
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerProductFormPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ProductService.get_manager_product_form_page(db, company_id)
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_management_companies(db: Session) -> list[dict[str, Any]] | None:
        cache_key = MANAGEMENT_COMPANIES_KEY
        cached = redis_client.get(cache_key)
        if cached:
            return msgpack.unpackb(cached, raw=False)

        companies = ManagementCompanyService.get_companies(db)
        if not companies:
            return None
        payload = [ManagementCompanyRead.model_validate(c).model_dump(mode="json") for c in companies]
        redis_client.setex(cache_key, TTL_SECONDS, msgpack.packb(payload))
        return payload

