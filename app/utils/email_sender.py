import resend

from app.config.settings import settings


def send_email(to_email:str, subject:str, body:str) -> None:
    # DEBUG: print the email (including any tokens) instead of sending it.
    if settings.DEBUG:
        print(f"\n--- DEV EMAIL (Resend not delivering) ---\nTo: {to_email}\nSubject: {subject}\n{body}\n--- END DEV EMAIL ---\n")
        return

    resend.api_key = settings.RESEND_API_KEY

    try:
        resend.Emails.send({
            "from": settings.FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": body,
        })
    except Exception as e:
        # Runs in a Celery worker with no caller to report to, so log and continue.
        print(f"send_email to {to_email} failed: {e}")