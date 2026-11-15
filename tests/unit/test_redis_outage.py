import inspect
import logging
import uuid
from unittest.mock import patch

import pytest
import redis
from kombu.exceptions import OperationalError

from app.cache import guards
from app.cache.invalidation import CacheInvalidation
from tests.conftest import fake_redis

# ───────────────────────────────────────────────────────────────
# Redis outage (bugs.md #11), unit level: the cache guards and email dispatch with Redis or the
# Celery broker unreachable. Tests marked "Guard" pass already and must keep passing: they pin down
# that a healthy Redis still behaves exactly as before. tests/integration/test_redis_outage.py
# covers the same over real HTTP.
# ───────────────────────────────────────────────────────────────


@pytest.fixture
def redis_down(monkeypatch):
    """Every Redis command the app uses raises, as when the server is unreachable."""
    def unreachable(*args, **kwargs):
        raise redis.ConnectionError("Error connecting to redis:6379")

    for command in ("get", "setex", "set", "delete", "keys", "incr", "ttl", "pipeline"):
        monkeypatch.setattr(fake_redis, command, unreachable)


# ─── cache_get / cache_set ─────────────────────────────────────

def test_cache_get_returns_the_value_when_redis_is_up():
    # Guard
    fake_redis.set("guard:key", b"value")
    assert guards.cache_get("guard:key") == b"value"
    assert guards.cache_get("guard:missing") is None


def test_cache_get_is_a_miss_when_redis_is_down(redis_down, caplog):
    with caplog.at_level(logging.WARNING, logger="app.cache.guards"):
        assert guards.cache_get("any:key") is None
    assert caplog.records, "the outage should be logged"


def test_cache_set_writes_when_redis_is_up():
    # Guard
    guards.cache_set("guard:set", 60, b"value")
    assert fake_redis.get("guard:set") == b"value"
    assert 0 < fake_redis.ttl("guard:set") <= 60


def test_cache_set_is_skipped_when_redis_is_down(redis_down, caplog):
    with caplog.at_level(logging.WARNING, logger="app.cache.guards"):
        guards.cache_set("any:key", 60, b"value")  # must not raise
    assert caplog.records


# ─── best_effort ───────────────────────────────────────────────

def test_best_effort_passes_through_when_nothing_fails():
    # Guard
    @guards.best_effort
    def clear(x):
        return x * 2

    assert clear(21) == 42
    assert clear.__name__ == "clear"


def test_best_effort_swallows_a_redis_error_and_logs_which_call(caplog):
    @guards.best_effort
    def delete_cached_something():
        raise redis.ConnectionError("down")

    with caplog.at_level(logging.WARNING, logger="app.cache.guards"):
        assert delete_cached_something() is None
    assert "delete_cached_something" in caplog.text


def test_best_effort_lets_other_errors_through():
    # Guard: only Redis errors are expected; anything else is a bug and must surface.
    @guards.best_effort
    def broken():
        raise KeyError("a real bug")

    with pytest.raises(KeyError):
        broken()


def _invalidation_methods():
    return [
        (name, fn) for name, fn in inspect.getmembers(CacheInvalidation, inspect.isfunction)
        if name.startswith("delete_")
    ]


@pytest.mark.parametrize("name", [name for name, _ in _invalidation_methods()])
def test_every_cache_clear_survives_redis_down(name, redis_down):
    fn = getattr(CacheInvalidation, name)
    args = [uuid.uuid4() for _ in inspect.signature(fn).parameters]
    fn(*args)  # must not raise


# ─── cached reads fall back to Postgres ────────────────────────

def test_cached_store_page_is_built_from_the_database_when_redis_is_down(redis_down):
    from app.cache.cache_service import CacheService
    from app.schema.marketplace import StorePageRead

    page = StorePageRead(products=[], groups=[])
    with patch("app.cache.cache_service.ProductService.get_store_page", return_value=page) as built:
        assert CacheService.get_cached_store_page(db=None) == page
    built.assert_called_once()


def test_cached_product_list_is_built_from_the_database_when_redis_is_down(redis_down):
    from app.cache.cache_service import CacheService

    with patch("app.cache.cache_service.ProductService.list_of_products", return_value=[]):
        assert CacheService.get_cached_products(db=None) == []


# ─── dispatch_email ────────────────────────────────────────────

def test_dispatch_email_queues_the_task(_no_real_celery_dispatch):
    # Guard
    from app.utils.email_dispatch import dispatch_email

    dispatch_email("fan@example.com", "Subject", "Body")

    _no_real_celery_dispatch.assert_called_once_with(
        "app.tasks.email.send_email", args=["fan@example.com", "Subject", "Body"]
    )


@pytest.mark.parametrize("error", [OperationalError("broker down"), redis.ConnectionError("down")])
def test_dispatch_email_survives_an_unreachable_broker(_no_real_celery_dispatch, error, caplog):
    from app.utils.email_dispatch import dispatch_email

    _no_real_celery_dispatch.side_effect = error
    with caplog.at_level(logging.WARNING, logger="app.utils.email_dispatch"):
        dispatch_email("fan@example.com", "Subject", "Body")  # must not raise
    assert "fan@example.com" in caplog.text or "Subject" in caplog.text
