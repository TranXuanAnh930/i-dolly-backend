from unittest.mock import patch

from app.cache.redis_client import make_redis_client


def test_client_has_short_timeouts():
    with patch("app.cache.redis_client.settings.REDIS_SOCKET_TIMEOUT", 1.0):
        kwargs = make_redis_client().connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == 1.0
    assert kwargs["socket_timeout"] == 1.0


def test_timeout_comes_from_settings():
    with patch("app.cache.redis_client.settings.REDIS_SOCKET_TIMEOUT", 0.25):
        kwargs = make_redis_client().connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == 0.25


def test_retries_once_without_backoff():
    retry = make_redis_client().get_retry()
    assert retry.get_retries() == 1
