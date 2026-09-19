from typing import Any, Literal

import msgpack
from sqlalchemy.orm import Session

from app.cache.redis_client import redis_client
from app.schema.marketplace import ProductRead, StorePageRead
from app.services.marketplace.product_service import ProductService


def get_cached_products(db:Session) -> list[dict[str, Any]]:
    cache_key = "products:list"
    cached = redis_client.get(cache_key)
    if cached:
        return msgpack.unpackb(cached, raw=False)
    products = ProductService.list_of_products(db)

    if not products:
        return []

    # One ProductRead per row, not one call on the whole list — model_validate
    # validates a single instance, not a collection. ProductRead also has no
    # from_attributes config, so it needs a dict, not the raw Product row;
    # category is the one field that still needs manual resolution either way
    # (category_id -> Category.name isn't something Pydantic can infer from a
    # plain dict), but every other field now comes from the real schema
    # instead of a second hand-typed field list, so a renamed/added/removed
    # ProductRead field surfaces as a loud validation error here, not a silent
    # drift between this cache and the schema.
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
    redis_client.setex(cache_key, 60 * 5, msgpack.packb(payload))
    return payload

def get_cached_store_page(db: Session) -> StorePageRead | Literal[False]:
    cache_key = "products:store_page"
    cached = redis_client.get(cache_key)
    if cached:
        return StorePageRead.model_validate(msgpack.unpackb(cached, raw=False))

    # get_store_page already returns a real StorePageRead instance (nested
    # ORM objects — Genre, Group — resolved via each nested model's
    # from_attributes config), so this cache can't diverge from the schema
    # without a validation error at write time. model_dump(mode="json") turns
    # it into the UUID-as-str / date-as-isoformat-string shapes msgpack can
    # store; the cache-hit branch above reconstructs the same StorePageRead
    # from that stored dict.
    result = ProductService.get_store_page(db)
    if not result:
        return False

    payload = result.model_dump(mode="json")
    redis_client.setex(cache_key, 60 * 5, msgpack.packb(payload))
    return result


def delete_cached_products() -> None:
    redis_client.delete("products:list")
    redis_client.delete("products:store_page")