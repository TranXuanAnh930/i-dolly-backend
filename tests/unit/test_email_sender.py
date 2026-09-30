from unittest.mock import patch

from app.utils import email_sender

MODULE = "app.utils.email_sender"


def test_debug_prints_instead_of_sending(capsys):
    with patch(f"{MODULE}.settings.DEBUG", True), patch(f"{MODULE}.resend.Emails.send") as send:
        email_sender.send_email("fan@example.com", "Verify", "token-123")
    send.assert_not_called()
    out = capsys.readouterr().out
    assert "fan@example.com" in out and "token-123" in out


def test_sends_through_resend():
    with patch(f"{MODULE}.settings.DEBUG", False), \
         patch(f"{MODULE}.settings.RESEND_API_KEY", "re_key"), \
         patch(f"{MODULE}.settings.FROM_EMAIL", "noreply@example.com"), \
         patch(f"{MODULE}.resend.Emails.send") as send:
        email_sender.send_email("fan@example.com", "Subject", "<p>Body</p>")

    assert email_sender.resend.api_key == "re_key"
    send.assert_called_once_with({
        "from": "noreply@example.com",
        "to": "fan@example.com",
        "subject": "Subject",
        "html": "<p>Body</p>",
    })


def test_delivery_failure_is_logged_not_raised(capsys):
    with patch(f"{MODULE}.settings.DEBUG", False), \
         patch(f"{MODULE}.resend.Emails.send", side_effect=RuntimeError("rejected")):
        email_sender.send_email("fan@example.com", "Subject", "Body")
    assert "rejected" in capsys.readouterr().out
