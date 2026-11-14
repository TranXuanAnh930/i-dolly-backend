import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.config.settings import settings


def make_redis_client() -> redis.Redis:
    # Fail fast when Redis is down instead of holding a request thread (and its DB connection):
    # short socket timeouts, and one immediate retry instead of redis-py's default of three with
    # exponential backoff (about 11 s against an unreachable host). The one retry still covers a
    # pooled connection that went stale when Redis restarted. Worst case: about 2 x the timeout.
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=False,
        socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        retry=Retry(NoBackoff(), retries=1),
        health_check_interval=30,
    )


redis_client = make_redis_client()
