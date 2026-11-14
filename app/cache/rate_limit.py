import hashlib
import ipaddress
from collections.abc import Callable

import redis
from fastapi import Depends, HTTPException, Request

from app.cache.redis_client import redis_client
from app.config.settings import settings
from app.db.models.identity import Users
from app.deps.auth import get_current_user, get_current_user_optional

# Per-account limits, on top of the IP limits: an attacker with many real IPs still gets only
# this many tries per email.
LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_WINDOW = 15 * 60
FORGOT_PASSWORD_LIMIT = 3
FORGOT_PASSWORD_WINDOW = 60 * 60


def _route_key(request: Request) -> str:
    # Use the route template (e.g. "/order/single_placed_order/{order_id}"), so every id shares one
    # budget. request.url.path is a fallback if no route matched.
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path

def client_ip(request:Request) -> str:
    """The visitor's IP, for rate limiting.

    Each trusted proxy appends the address it received the request from to X-Forwarded-For, so
    with TRUSTED_PROXY_HOPS proxies in front the visitor is that many entries from the right.
    Everything further left was written by the client and is ignored. Falls back to the peer
    address when no proxy is trusted, the header is shorter than expected, or the entry isn't an IP.
    """
    peer = request.client.host
    hops = settings.TRUSTED_PROXY_HOPS
    if hops <= 0:
        return peer
    entries = [entry.strip() for value in request.headers.getlist("x-forwarded-for") for entry in value.split(",")]
    if len(entries) < hops:
        return peer
    try:
        return str(ipaddress.ip_address(entries[-hops]))
    except ValueError:
        return peer

def ip_key(request:Request) -> str:
    return f"rate:ip:{_route_key(request)}:{client_ip(request)}"

# user_key and user_or_ip_key read request.state.user, which the auth dependencies set.
# rate_limit() makes its limiter depend on that auth dependency itself, so the user is there
# whatever order a route lists its dependencies in.

def user_key(request:Request) -> str:
    user = request.state.user
    return f"rate:user:{_route_key(request)}:{user.id}"

def user_or_ip_key(request:Request) -> str:
    # For auth-optional routes: a guest has no user to key on, so falls back to ip_key's bucket.
    user = getattr(request.state, "user", None)
    if user is not None:
        return f"rate:user:{_route_key(request)}:{user.id}"
    return ip_key(request)

def _increment(key:str, window:int) -> int:
    # One MULTI transaction: the key is created with its TTL before it's incremented, so a
    # counter can never exist without an expiry.
    pipe = redis_client.pipeline(transaction=True)
    pipe.set(key, 0, ex=window, nx=True)
    pipe.incr(key)
    _, count = pipe.execute()
    return int(count)

def rate_limit(limit:int, window:int, key_func: Callable[[Request], str]) -> Callable[..., None]:
    def check(request:Request) -> None:
        try:
            key = key_func(request)
            count = _increment(key, window)

            if count > limit:
                ttl = redis_client.ttl(key)
                if ttl<0:
                    ttl = window
                raise HTTPException(status_code=429, detail=f"Too many requests. Please try again after {ttl} seconds.")
        except redis.RedisError:
            print("Rate limiter Internal Error")
        return

    # FastAPI runs a dependency once per request, so a route that also declares the same auth
    # dependency doesn't authenticate twice. A user-keyed limiter on a route with no auth
    # dependency now answers 401 instead of failing with a 500.
    if key_func is user_key:
        def user_limiter(request:Request, _user:Users=Depends(get_current_user)) -> None:
            check(request)
        return user_limiter
    if key_func is user_or_ip_key:
        def user_or_ip_limiter(request:Request, _user:Users | None=Depends(get_current_user_optional)) -> None:
            check(request)
        return user_or_ip_limiter
    return check


# --- Per-account limits. Keyed by a hash of the email, so the key has a fixed size whatever the
# client sends and no address is stored in Redis. They count every email the same way, registered
# or not, so a 429 doesn't reveal whether an account exists. Like rate_limit(), they fail open on
# a Redis error.

def _email_key(scope:str, email:str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"rate:{scope}:{digest}"

def login_attempts_exceeded(email:str) -> bool:
    try:
        count = redis_client.get(_email_key("login_fail", email))
        return count is not None and int(count) >= LOGIN_FAIL_LIMIT
    except redis.RedisError:
        print("Rate limiter Internal Error")
        return False

def record_login_failure(email:str) -> None:
    try:
        _increment(_email_key("login_fail", email), LOGIN_FAIL_WINDOW)
    except redis.RedisError:
        print("Rate limiter Internal Error")

def clear_login_failures(email:str) -> None:
    try:
        redis_client.delete(_email_key("login_fail", email))
    except redis.RedisError:
        print("Rate limiter Internal Error")

def forgot_password_limit_exceeded(email:str) -> bool:
    """Count one reset request for this email; True once it is over the hourly limit."""
    try:
        return _increment(_email_key("forgot_password", email), FORGOT_PASSWORD_WINDOW) > FORGOT_PASSWORD_LIMIT
    except redis.RedisError:
        print("Rate limiter Internal Error")
        return False
