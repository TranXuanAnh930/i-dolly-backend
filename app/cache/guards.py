"""Keep a Redis outage from turning into a site outage.

The cache is an optimization: when Redis is unavailable, reads should be answered from Postgres and
cache clears after a write should be skipped, never failed.
"""
import functools
import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from redis import RedisError

from app.cache.redis_client import redis_client

P = ParamSpec("P")
R = TypeVar("R")
logger = logging.getLogger(__name__)


def cache_get(key: str) -> bytes | None:
    """The cached value for `key`, or None on a miss. A Redis error counts as a miss."""
    try:
        return redis_client.get(key)
    except RedisError as e:
        logger.warning("Cache get for %s skipped, Redis unavailable: %s", key, e)
        return None


def cache_set(key: str, ttl_seconds: int, value: bytes) -> None:
    """Cache `value` for `ttl_seconds`. A Redis error skips the write; the caller already has the
    value it just built."""
    try:
        redis_client.set(key, value, ex=ttl_seconds)
    except RedisError as e:
        logger.warning("Cache set for %s skipped, Redis unavailable: %s", key, e)


def best_effort(func: Callable[P, R]) -> Callable[P, R | None]:
    """Decorator for cache clears that run after a commit: a Redis error is logged and the call
    returns None instead of raising. Any other exception still raises."""
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        try:
            return func(*args, **kwargs)
        except RedisError as e:
            logger.warning("Cache clear for %s skipped, Redis unavailable: %s", func.__name__, e)
            return None
    return wrapper
