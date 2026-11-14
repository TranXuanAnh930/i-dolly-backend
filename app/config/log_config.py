import logging
import sys

from app.config.settings import settings

# Every module logs through logging.getLogger(__name__), so all of the app's loggers sit under
# "app"; LOG_LEVEL applies to that branch only. Records propagate to the root logger, whose handler
# writes them out: the one added here under uvicorn, or Celery's own in the worker, which replaces
# the root handlers when it starts. Library loggers keep the root's default WARNING level.
APP_LOGGER = "app"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    """Safe to call more than once: the API (main.py) and the Celery app (app/celery_app.py) both
    call it, and one process can import both."""
    logging.getLogger(APP_LOGGER).setLevel(settings.LOG_LEVEL.upper())
    # A no-op when the root logger already has a handler.
    logging.basicConfig(stream=sys.stdout, format=LOG_FORMAT)
