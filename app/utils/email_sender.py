import resend
from app.config.settings import settings


def send_email(to_email:str, subject:str, body:str) -> None:
    # Dev convenience (settings.DEBUG, default false — see its own comment): print the
    # token-bearing body and stop, instead of also attempting a real send. The old version printed
    # then sent anyway, on the assumption that the API key is always a placeholder in local dev so
    # the real send would just fail harmlessly — that assumption breaks the moment someone
    # configures a real key locally (e.g. to test the email flow end to end), and it was silently
    # spending real email-provider quota on every test run that reached this function through an
    # unmocked Celery dispatch.
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
        # Runs inside a Celery worker, not the request/response cycle — there's no
        # caller left to raise to, so log and move on.
        print(f"send_email to {to_email} failed: {e}")