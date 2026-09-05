# Placeholder task proving the worker/broker/backend wiring works end to end.
# No real domain logic belongs here — see docs/project_status.md for which
# background jobs (lottery draw, async email, ETL) are still undecided.
from app.celery_app import celery_app


@celery_app.task(name="app.tasks.example.ping")
def ping() -> str:
    return "pong"
