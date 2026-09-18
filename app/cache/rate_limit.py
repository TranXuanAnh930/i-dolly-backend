import redis
from fastapi import HTTPException, Request

from app.cache.redis_client import redis_client


def _route_key(request: Request) -> str:
    # The route's raw path template (e.g. "/order/single_placed_order/{order_id}"),
    # not the resolved URL — so two calls against the same endpoint with
    # different ids share a budget instead of each id getting its own bucket.
    # Populated by Starlette once routing has matched, which is always true by
    # the time a Depends() runs; request.url.path is a defensive fallback only.
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path

def ip_key(request:Request):
    return f"rate:ip:{_route_key(request)}:{request.client.host}"

def user_key(request:Request):
    user = request.state.user
    return f"rate:user:{_route_key(request)}:{user.id}"

def rate_limit(limit:int, window:int, key_func):
    def limiter(request:Request):
        try:
            key = key_func(request)
            count = redis_client.incr(key)   # atomically: create at 1 if missing, else +1
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