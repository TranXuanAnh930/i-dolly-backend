import logging
from unittest.mock import patch

from app.utils import email_sender

MODULE = "app.utils.email_sender"


def test_debug_logs_instead_of_sending(caplog):
    with caplog.at_level(logging.INFO, logger=MODULE), \
         patch(f"{MODULE}.settings.DEBUG", True), patch(f"{MODULE}.resend.Emails.send") as send:
        email_sender.send_email("fan@example.com", "Verify", "token-123")
    send.assert_not_called()
    [record] = caplog.records
    assert record.levelno == logging.INFO
    assert "fan@example.com" in record.getMessage() and "token-123" in record.getMessage()


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


def test_delivery_failure_is_logged_not_raised(caplog):
    with caplog.at_level(logging.INFO, logger=MODULE), \
         patch(f"{MODULE}.settings.DEBUG", False), \
         patch(f"{MODULE}.resend.Emails.send", side_effect=RuntimeError("rejected")):
        email_sender.send_email("fan@example.com", "Subject", "Body")
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "fan@example.com" in record.getMessage()
    # The traceback is attached, so the reason ("rejected") reaches the log.
    assert record.exc_info is not None and "rejected" in str(record.exc_info[1])
