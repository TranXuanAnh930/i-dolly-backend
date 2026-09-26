from collections.abc import Callable

import redis
from fastapi import HTTPException, Request

from app.cache.redis_client import redis_client


def _route_key(request: Request) -> str:
    # Use the route template (e.g. "/order/single_placed_order/{order_id}"), so every id shares one
    # budget. request.url.path is a fallback if no route matched.
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path

def ip_key(request:Request) -> str:
    return f"rate:ip:{_route_key(request)}:{request.client.host}"

def user_key(request:Request) -> str:
    user = request.state.user
    return f"rate:user:{_route_key(request)}:{user.id}"

def rate_limit(limit:int, window:int, key_func: Callable[[Request], str]) -> Callable[[Request], None]:
    def limiter(request:Request) -> None:
        try:
            key = key_func(request)
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, window) 

            if int(count) > limit:
                ttl = redis_client.ttl(key)
                if ttl<0:
                    ttl = window
                raise HTTPException(status_code=429, detail=f"Too many requests. Please try again after {ttl} seconds.")
        except redis.RedisError:
            print("Rate limiter Internal Error")
        return
    return limiter