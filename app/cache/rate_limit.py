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

def user_or_ip_key(request:Request) -> str:
    # For auth-optional routes (get_current_user_optional), which only sets
    # request.state.user when a token was actually presented — a guest has
    # no user to key on, so falls back to ip_key's bucket instead of raising.
    user = getattr(request.state, "user", None)
    if user is not None:
        return f"rate:user:{_route_key(request)}:{user.id}"
    return ip_key(request)

def rate_limit(limit:int, window:int, key_func: Callable[[Request], str]) -> Callable[[Request], None]:
    def limiter(request:Request) -> None:
        try:
            key = key_func(request)
            # One MULTI transaction: the key is created with its TTL before it's incremented, so a
            # counter can never exist without an expiry.
            pipe = redis_client.pipeline(transaction=True)
            pipe.set(key, 0, ex=window, nx=True)
            pipe.incr(key)
            _, count = pipe.execute()

            if int(count) > limit:
                ttl = redis_client.ttl(key)
                if ttl<0:
                    ttl = window
                raise HTTPException(status_code=429, detail=f"Too many requests. Please try again after {ttl} seconds.")
        except redis.RedisError:
            print("Rate limiter Internal Error")
        return
    return limiter