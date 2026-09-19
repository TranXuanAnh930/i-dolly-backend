from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.config.settings import settings


def send_email(to_email:str, subject:str, body:str) -> None:
    # Dev convenience (settings.DEBUG, default false — see its own comment):
    # print the token-bearing body up front, before attempting a real send,
    # since SENDGRID_API_KEY is a placeholder in most local setups and the
    # send below will fail either way.
    if settings.DEBUG:
        print(f"\n--- DEV EMAIL (SendGrid not delivering) ---\nTo: {to_email}\nSubject: {subject}\n{body}\n--- END DEV EMAIL ---\n")

    msg = Mail(
        from_email=settings.FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        plain_text_content=body
    )

    sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
    try:
        sg.send(msg)
    except Exception as e:
        # Runs inside a FastAPI BackgroundTask, after the response has
        # already gone out — there's no request left to fail, so raising
        # here would only surface as an unhandled-exception traceback in
        # the server log with no token in it (the dev print above already
        # covers that). Log and move on either way.
        print(f"send_email to {to_email} failed: {e}")