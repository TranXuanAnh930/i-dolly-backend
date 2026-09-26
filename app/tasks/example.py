# Placeholder task for checking the Celery worker/broker wiring.
from app.celery_app import celery_app


@celery_app.task(name="app.tasks.example.ping")
def ping() -> str:
    return "pong"
