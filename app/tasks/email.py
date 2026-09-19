from app.celery_app import celery_app
from app.utils.email_sender import send_email as deliver_email


@celery_app.task(name="app.tasks.email.send_email")
def send_email(user_email: str, email_title: str, email_body: str) -> None:
    deliver_email(user_email, email_title, email_body)