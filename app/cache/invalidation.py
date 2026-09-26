"""Cache keys and invalidation.

Depends only on Redis, so services can invalidate cache entries without importing CacheService
(which imports services to fill the cache). CacheService inherits these methods.
"""
import uuid

from app.cache.redis_client import redis_client

TTL_SECONDS = 60 * 5

PRODUCTS_LIST_KEY = "products:list"
STORE_PAGE_KEY = "products:store_page"
EVENTS_PAGE_KEY = "concerts:events_page"
MEMBERS_PAGE_KEY = "idols:members_page"
GROUPS_PAGE_KEY = "groups:groups_page"
VENUES_KEY = "venues:all"
IDOL_COLORS_KEY = "idol_colors:all"
MANAGER_IDOLS_PAGE_KEY = "idols:manager_idols_page"
MANAGER_IDOL_FORM_PAGE_KEY = "idols:manager_idol_form_page"
MANAGER_GROUPS_PAGE_KEY = "groups:manager_groups_page"
MANAGER_EVENTS_PAGE_KEY = "concerts:manager_events_page"
MANAGEMENT_COMPANIES_KEY = "management_companies:all"


def product_detail_key(id: uuid.UUID) -> str:
    return f"products:{id}:detail"


def concert_detail_key(id: uuid.UUID) -> str:
    return f"concerts:{id}:detail"


def idol_detail_key(id: uuid.UUID) -> str:
    return f"idols:detail:{id}"


def group_detail_key(id: uuid.UUID) -> str:
    return f"groups:detail:{id}"


# Manager product pages are cached per company_id; None (admin) shares the "all" entry.
def manager_products_page_key(company_id: uuid.UUID | None) -> str:
    return f"products:manager_products_page:{company_id if company_id else 'all'}"


def manager_product_form_page_key(company_id: uuid.UUID | None) -> str:
    return f"products:manager_product_form_page:{company_id if company_id else 'all'}"


def _delete_matching(pattern: str) -> None:
    # keys() is an O(N) scan; fine at this key count, use SCAN if that grows.
    keys = redis_client.keys(pattern)
    if keys:
        redis_client.delete(*keys)


class CacheInvalidation:

    @staticmethod
    def delete_cached_products() -> None:
        redis_client.delete(PRODUCTS_LIST_KEY)
        redis_client.delete(STORE_PAGE_KEY)

    # Recommendations make each detail page depend on other products, so any product write clears
    # the whole detail-page namespace.
    @staticmethod
    def delete_cached_product_details() -> None:
        _delete_matching(product_detail_key("*"))

    @staticmethod
    def delete_cached_events_page() -> None:
        redis_client.delete(EVENTS_PAGE_KEY)

    # Every write that affects a concert detail knows its concert_id, so this deletes one key.
    @staticmethod
    def delete_cached_concert_detail(id: uuid.UUID) -> None:
        redis_client.delete(concert_detail_key(id))

    @staticmethod
    def delete_cached_members_page() -> None:
        redis_client.delete(MEMBERS_PAGE_KEY)

    # Idol and group detail pages embed each other's data, so any idol or group write clears both
    # namespaces.
    @staticmethod
    def delete_cached_idol_details() -> None:
        _delete_matching(idol_detail_key("*"))

    @staticmethod
    def delete_cached_groups_page() -> None:
        redis_client.delete(GROUPS_PAGE_KEY)

    @staticmethod
    def delete_cached_group_details() -> None:
        _delete_matching(group_detail_key("*"))

    @staticmethod
    def delete_cached_venues() -> None:
        redis_client.delete(VENUES_KEY)

    @staticmethod
    def delete_cached_idol_colors() -> None:
        redis_client.delete(IDOL_COLORS_KEY)

    @staticmethod
    def delete_cached_manager_idols_page() -> None:
        redis_client.delete(MANAGER_IDOLS_PAGE_KEY)

    @staticmethod
    def delete_cached_manager_idol_form_page() -> None:
        redis_client.delete(MANAGER_IDOL_FORM_PAGE_KEY)

    @staticmethod
    def delete_cached_manager_groups_page() -> None:
        redis_client.delete(MANAGER_GROUPS_PAGE_KEY)

    @staticmethod
    def delete_cached_manager_events_page() -> None:
        redis_client.delete(MANAGER_EVENTS_PAGE_KEY)

    # Product has no company_id column, so a product write clears every company's entry.
    @staticmethod
    def delete_cached_manager_products_pages() -> None:
        _delete_matching(manager_products_page_key("*"))
        _delete_matching(manager_product_form_page_key("*"))

    @staticmethod
    def delete_cached_management_companies() -> None:
        redis_client.delete(MANAGEMENT_COMPANIES_KEY)
