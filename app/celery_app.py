from celery import Celery

from app.config.settings import settings

# Same Redis instance as the cache, on a separate DB index (CELERY_BROKER_DB).
_redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.CELERY_BROKER_DB}"

celery_app = Celery(
    "i_dolly",
    broker=_redis_url,
    backend=_redis_url,
    include=["app.tasks.example", "app.tasks.lottery", "app.tasks.email"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
