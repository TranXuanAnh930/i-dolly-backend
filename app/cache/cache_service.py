import uuid
from typing import Any, Literal

import msgpack
from sqlalchemy.orm import Session

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

_TTL_SECONDS = 60 * 5


# One class rather than a flat module of functions, matching the router/service
# layer's convention (IdolService, GroupService, ...) — every method is a
# @staticmethod, called as CacheService.method(...), including cross-calls
# between methods on this same class.
class CacheService:

    @staticmethod
    def get_cached_products(db: Session) -> list[dict[str, Any]]:
        cache_key = "products:list"
        cached = redis_client.get(cache_key)
        if cached:
            return msgpack.unpackb(cached, raw=False)
        products = ProductService.list_of_products(db)

        if not products:
            return []

        # ProductRead has no from_attributes config, so it validates a dict, not the raw Product row —
        # category still needs manual resolution (category_id -> Category.name), but every other
        # field goes through the real schema so a renamed field fails loudly here, not silently.
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
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(payload))
        return payload

    @staticmethod
    def get_cached_store_page(db: Session) -> StorePageRead | Literal[False]:
        cache_key = "products:store_page"
        cached = redis_client.get(cache_key)
        if cached:
            return StorePageRead.model_validate(msgpack.unpackb(cached, raw=False))

        # get_store_page already returns a real StorePageRead instance, so this cache can't diverge
        # from the schema. model_dump(mode="json") gives msgpack-storable values; the cache-hit branch
        # above reconstructs the same StorePageRead from that stored dict.
        result = ProductService.get_store_page(db)
        if not result:
            return False

        payload = result.model_dump(mode="json")
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(payload))
        return result

    @staticmethod
    def delete_cached_products() -> None:
        redis_client.delete("products:list")
        redis_client.delete("products:store_page")

    @staticmethod
    def get_cached_product_detail(db: Session, id: uuid.UUID) -> ProductDetailRead | Literal[False]:
        cache_key = f"products:{id}:detail"
        cached = redis_client.get(cache_key)
        if cached:
            return ProductDetailRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ProductService.get_product_detail(db, id)
        if not result:
            return False
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    # Recommendations are built from every other product (same-artist, or same-genre for
    # album-family items), so a write to any product can shift what shows on some OTHER
    # product's cached detail page too — the write has no cheap way to know which ids' pages
    # that touches. Same fan-out tradeoff as delete_cached_idol_details below: clear the whole
    # namespace rather than resolve the affected set.
    @staticmethod
    def delete_cached_product_details() -> None:
        keys = redis_client.keys("products:*:detail")
        if keys:
            redis_client.delete(*keys)

    @staticmethod
    def get_cached_events_page(db: Session) -> EventsPageRead | Literal[False]:
        cache_key = "concerts:events_page"
        cached = redis_client.get(cache_key)
        if cached:
            return EventsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ConcertService.get_events_page(db)
        if not result:
            return False
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def delete_cached_events_page() -> None:
        redis_client.delete("concerts:events_page")

    # Caches ConcertService.get_concert_detail_public only — the personalized fields
    # (has_ticket/has_won_lottery/entered_campaign_ids/my_lottery_preferences) are never part of
    # this payload, so a cache hit here can never leak one fan's ticket/lottery state to
    # another. The router merges those in fresh on every request, cached or not.
    @staticmethod
    def get_cached_concert_detail(db: Session, id: uuid.UUID) -> ConcertDetailRead | Literal[False]:
        cache_key = f"concerts:{id}:detail"
        cached = redis_client.get(cache_key)
        if cached:
            return ConcertDetailRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ConcertService.get_concert_detail_public(db, id)
        if not result:
            return False
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    # Unlike delete_cached_idol_details/delete_cached_product_details, every mutation that can
    # change this bundle (the concert itself, one of its ticket types, a lottery/direct-sale
    # campaign, a performer credit) always knows its own concert_id — no cross-id fan-out to
    # resolve, so this is a precise single-key delete rather than a namespace scan.
    @staticmethod
    def delete_cached_concert_detail(id: uuid.UUID) -> None:
        redis_client.delete(f"concerts:{id}:detail")

    @staticmethod
    def get_cached_members_page(db: Session) -> MembersPageRead | Literal[False]:
        cache_key = "idols:members_page"
        cached = redis_client.get(cache_key)
        if cached:
            return MembersPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = IdolService.get_members_page(db)
        if not result:
            return False
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def delete_cached_members_page() -> None:
        redis_client.delete("idols:members_page")

    @staticmethod
    def get_cached_idol_detail(db: Session, id: uuid.UUID) -> IdolDetailRead | Literal[False]:
        cache_key = f"idols:detail:{id}"
        cached = redis_client.get(cache_key)
        if cached:
            return IdolDetailRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = IdolService.get_idol_detail(db, id)
        if not result:
            return False
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    # An idol detail page embeds its group and its siblings (other idols sharing
    # that group_id), and a group detail page embeds every member's idol data —
    # so a write to either an idol or a group can invalidate detail pages keyed
    # by ids this method was never given (e.g. renaming a group must bust the
    # detail cache of idols this call has no id for). Resolving exactly which
    # ids are affected isn't cheap; clearing the whole namespace is, and both
    # caches are only ever written together for that reason — same tradeoff as
    # delete_cached_manager_products_pages below.
    @staticmethod
    def delete_cached_idol_details() -> None:
        keys = redis_client.keys("idols:detail:*")
        if keys:
            redis_client.delete(*keys)

    @staticmethod
    def get_cached_groups_page(db: Session) -> GroupsPageRead | Literal[False]:
        cache_key = "groups:groups_page"
        cached = redis_client.get(cache_key)
        if cached:
            return GroupsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = GroupService.get_groups_page(db)
        if not result:
            return False
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def delete_cached_groups_page() -> None:
        redis_client.delete("groups:groups_page")

    @staticmethod
    def get_cached_group_detail(db: Session, id: uuid.UUID) -> GroupDetailRead | Literal[False]:
        cache_key = f"groups:detail:{id}"
        cached = redis_client.get(cache_key)
        if cached:
            return GroupDetailRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = GroupService.get_group_detail(db, id)
        if not result:
            return False
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    # Same cross-invalidation tradeoff as delete_cached_idol_details above — a
    # group detail page embeds its members' idol data, so it's cleared alongside
    # the idol detail cache on any idol or group write, not just group writes.
    @staticmethod
    def delete_cached_group_details() -> None:
        keys = redis_client.keys("groups:detail:*")
        if keys:
            redis_client.delete(*keys)

    # Venues and idol colors are near-static lookup tables (no store-facing personalization, no
    # money/inventory at stake) — same TTL+invalidate-on-write shape as the pages above, just a
    # smaller payload. VenueRead/IdolColorRead both have from_attributes=True, so no manual dict
    # construction is needed the way get_cached_products needs for ProductRead.

    @staticmethod
    def get_cached_venues(db: Session) -> list[dict[str, Any]] | Literal[False]:
        cache_key = "venues:all"
        cached = redis_client.get(cache_key)
        if cached:
            return msgpack.unpackb(cached, raw=False)

        venues = VenueService.get_venues(db)
        if not venues:
            return False
        payload = [VenueRead.model_validate(v).model_dump(mode="json") for v in venues]
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(payload))
        return payload

    @staticmethod
    def delete_cached_venues() -> None:
        redis_client.delete("venues:all")

    @staticmethod
    def get_cached_idol_colors(db: Session) -> list[dict[str, Any]] | Literal[False]:
        cache_key = "idol_colors:all"
        cached = redis_client.get(cache_key)
        if cached:
            return msgpack.unpackb(cached, raw=False)

        colors = IdolColorService.get_idol_colors(db)
        if not colors:
            return False
        payload = [IdolColorRead.model_validate(c).model_dump(mode="json") for c in colors]
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(payload))
        return payload

    @staticmethod
    def delete_cached_idol_colors() -> None:
        redis_client.delete("idol_colors:all")

    # --- Manager/admin settings pages. Unlike the store-facing pages above, these never 404 on an
    # empty result (an empty list is a normal state for a brand-new company) — the underlying service
    # functions always return a real page object, so there's no Literal[False] branch to cache around.

    @staticmethod
    def get_cached_manager_idols_page(db: Session) -> ManagerIdolsPageRead:
        cache_key = "idols:manager_idols_page"
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerIdolsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = IdolService.get_manager_idols_page(db)
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def delete_cached_manager_idols_page() -> None:
        redis_client.delete("idols:manager_idols_page")

    @staticmethod
    def get_cached_manager_idol_form_page(db: Session) -> ManagerIdolFormPageRead:
        cache_key = "idols:manager_idol_form_page"
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerIdolFormPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = IdolService.get_manager_idol_form_page(db)
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def delete_cached_manager_idol_form_page() -> None:
        redis_client.delete("idols:manager_idol_form_page")

    @staticmethod
    def get_cached_manager_groups_page(db: Session) -> ManagerGroupsPageRead:
        cache_key = "groups:manager_groups_page"
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerGroupsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = GroupService.get_manager_groups_page(db)
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def delete_cached_manager_groups_page() -> None:
        redis_client.delete("groups:manager_groups_page")

    @staticmethod
    def get_cached_manager_events_page(db: Session) -> ManagerEventsPageRead:
        cache_key = "concerts:manager_events_page"
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerEventsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ConcertService.get_manager_events_page(db)
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def delete_cached_manager_events_page() -> None:
        redis_client.delete("concerts:manager_events_page")

    # Products' manager pages are the only ones of this batch scoped by company_id (None means an
    # admin viewing every company's products unfiltered) — one cache entry per company_id rather than
    # one shared entry, so a manager editing their own catalog never sees another company's cached
    # page or vice versa. Invalidation clears every company's entry rather than tracking who's
    # affected by a given product edit — company_id isn't a column on Product itself (resolved
    # indirectly through album/merch detail, see product_service.resolve_product_company_ids), so
    # knowing exactly which company_id keys a given write touches isn't cheap; clearing all of them
    # is. `keys()` (an O(N) scan) is fine at this project's key-count; a real high-traffic deployment
    # would want a SCAN cursor or a company_id-indexed key registry instead.

    @staticmethod
    def _manager_products_cache_key(company_id: uuid.UUID | None) -> str:
        return f"products:manager_products_page:{company_id if company_id else 'all'}"

    @staticmethod
    def _manager_product_form_cache_key(company_id: uuid.UUID | None) -> str:
        return f"products:manager_product_form_page:{company_id if company_id else 'all'}"

    @staticmethod
    def get_cached_manager_products_page(db: Session, company_id: uuid.UUID | None) -> ManagerProductsPageRead:
        cache_key = CacheService._manager_products_cache_key(company_id)
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerProductsPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ProductService.get_manager_products_page(db, company_id)
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def get_cached_manager_product_form_page(db: Session, company_id: uuid.UUID | None) -> ManagerProductFormPageRead:
        cache_key = CacheService._manager_product_form_cache_key(company_id)
        cached = redis_client.get(cache_key)
        if cached:
            return ManagerProductFormPageRead.model_validate(msgpack.unpackb(cached, raw=False))

        result = ProductService.get_manager_product_form_page(db, company_id)
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(result.model_dump(mode="json")))
        return result

    @staticmethod
    def delete_cached_manager_products_pages() -> None:
        for pattern in ("products:manager_products_page:*", "products:manager_product_form_page:*"):
            keys = redis_client.keys(pattern)
            if keys:
                redis_client.delete(*keys)

    @staticmethod
    def get_cached_management_companies(db: Session) -> list[dict[str, Any]] | Literal[False]:
        cache_key = "management_companies:all"
        cached = redis_client.get(cache_key)
        if cached:
            return msgpack.unpackb(cached, raw=False)

        companies = ManagementCompanyService.get_companies(db)
        if not companies:
            return False
        payload = [ManagementCompanyRead.model_validate(c).model_dump(mode="json") for c in companies]
        redis_client.setex(cache_key, _TTL_SECONDS, msgpack.packb(payload))
        return payload

    @staticmethod
    def delete_cached_management_companies() -> None:
        redis_client.delete("management_companies:all")
