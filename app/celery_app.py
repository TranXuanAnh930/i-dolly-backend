from celery import Celery

from app.config.settings import settings

# Reuses the same Redis instance as app/cache/redis_client.py but a separate
# DB index (CELERY_BROKER_DB, default 1 vs. REDIS_DB's default 0) so Celery's
# broker/result keys never collide with the product-list cache or the rate
# limiter's counters.
_redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.CELERY_BROKER_DB}"

celery_app = Celery(
    "i_dolly",
    broker=_redis_url,
    backend=_redis_url,
    include=["app.tasks.example", "app.tasks.lottery"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
