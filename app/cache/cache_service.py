from sqlalchemy.orm import Session
from app.cache.redis_client import redis_client
from app.services.product_service import List_of_products
import msgpack
import uuid

def get_cached_products(db:Session):
    cache_key = "products:list"
    cached = redis_client.get(cache_key)
    if cached:
        return msgpack.unpackb(cached, raw=False)
    products = List_of_products(db)
    
    if not products:
        return []

    result = [
        {
            # str(...) — msgpack has no native UUID type and would raise on
            # a raw uuid.UUID; the API schema (uuid.UUID) parses this string
            # back into a UUID on the way out, same as any JSON id would.
            "id" : str(p.id),
            "name" : p.name,
            "price" : p.price,
            "description" : p.description,
            "quantity" : p.quantity,
            "image_url" : p.image_url,
            "category" : p.category.name if p.category else None
            
        }
        for p in products
    ]
    redis_client.setex(cache_key, 60 * 5, msgpack.packb(result))
    return result

def delete_cached_product(product_id: uuid.UUID):
    redis_client.delete("products:list")
    redis_client.delete(f"product:{product_id}")