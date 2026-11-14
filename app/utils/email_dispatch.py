import logging

from kombu.exceptions import OperationalError
from redis import RedisError

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


def dispatch_email(to_email: str, subject: str, body: str) -> None:
    """Queue a transactional email for the Celery worker. Called after a commit, so a broker that
    can't be reached must not fail the request: the failure is logged and the email is lost."""
    try:
        celery_app.send_task("app.tasks.email.send_email", args=[to_email, subject, body])
    except (OperationalError, RedisError) as e:
        logger.warning("Failed to dispatch email subject '%s' to %s: %s", subject, to_email, e)
