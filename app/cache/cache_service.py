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
    redis_client.setex(cache_key, 60 * 5, msgpack.packb(payload))
    return payload

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
    redis_client.setex(cache_key, 60 * 5, msgpack.packb(payload))
    return result


def delete_cached_products() -> None:
    redis_client.delete("products:list")
    redis_client.delete("products:store_page")