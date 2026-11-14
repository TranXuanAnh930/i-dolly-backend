import logging

import resend

from app.config.settings import settings

logger = logging.getLogger(__name__)


def send_email(to_email:str, subject:str, body:str) -> None:
    # DEBUG: log the email (including any tokens) instead of sending it.
    if settings.DEBUG:
        logger.info(
            "DEV EMAIL (not sent)\nTo: %s\nSubject: %s\n%s\n--- END DEV EMAIL ---", to_email, subject, body
        )
        return

    resend.api_key = settings.RESEND_API_KEY

    try:
        resend.Emails.send({
            "from": settings.FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": body,
        })
    except Exception:
        # Runs in a Celery worker with no caller to report to, so log and continue. Not retried.
        logger.exception("send_email to %s failed (subject: %s)", to_email, subject)