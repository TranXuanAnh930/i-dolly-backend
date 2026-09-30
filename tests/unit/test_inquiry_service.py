import uuid
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.schema.shared import InquiryCreate, InquiryTopic

DEFAULT_ID = uuid.uuid4()
CONTENT = "When does the lottery for the Tokyo show close?"

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def make_mock_db(recent_count=0):
    db = MagicMock()
    db.query.return_value.filter.return_value.count.return_value = recent_count
    return db

def make_payload(email="Fan@Example.com", topic=InquiryTopic.lottery, content=CONTENT):
    return InquiryCreate(email=email, topic=topic, content=content)

# ───────────────────────────────────────────────────────────────
# Inquiry Service Tests
# ───────────────────────────────────────────────────────────────

class TestInquiryService:

    @patch("app.services.shared.inquiry_service.celery_app")
    def test_guest_inquiry_is_saved_and_confirmed(self, mock_celery):
        from app.services.shared.inquiry_service import InquiryService

        db = make_mock_db(recent_count=0)

        inquiry = InquiryService.submit_inquiry(db, make_payload(), None)

        db.add.assert_called_once_with(inquiry)
        db.commit.assert_called_once()
        assert inquiry.email == "fan@example.com"
        assert inquiry.user_id is None
        mock_celery.send_task.assert_called_once()
        to_address = mock_celery.send_task.call_args.kwargs["args"][0]
        assert to_address == "fan@example.com"

    @patch("app.services.shared.inquiry_service.celery_app")
    def test_logged_in_inquiry_is_linked_to_user(self, mock_celery):
        from app.services.shared.inquiry_service import InquiryService

        user = MagicMock()
        user.id = DEFAULT_ID

        inquiry = InquiryService.submit_inquiry(make_mock_db(), make_payload(), user)

        assert inquiry.user_id == DEFAULT_ID

    @patch("app.services.shared.inquiry_service.celery_app")
    def test_over_cap_saves_but_skips_email(self, mock_celery):
        from app.services.shared.inquiry_service import CONFIRMATIONS_PER_ADDRESS, InquiryService

        db = make_mock_db(recent_count=CONFIRMATIONS_PER_ADDRESS)

        InquiryService.submit_inquiry(db, make_payload(), None)

        db.commit.assert_called_once()
        mock_celery.send_task.assert_not_called()

    @patch("app.services.shared.inquiry_service.celery_app")
    def test_confirmation_does_not_echo_user_content(self, mock_celery):
        from app.services.shared.inquiry_service import InquiryService

        InquiryService.submit_inquiry(make_mock_db(), make_payload(), None)

        email_body = mock_celery.send_task.call_args.kwargs["args"][2]
        assert CONTENT not in email_body
        assert InquiryTopic.lottery.label in email_body

# ───────────────────────────────────────────────────────────────
# Request validation
# ───────────────────────────────────────────────────────────────

class TestInquiryCreate:

    def test_whitespace_only_content_rejected(self):
        with pytest.raises(ValidationError):
            make_payload(content=" " * 50)

    def test_overlong_content_rejected(self):
        with pytest.raises(ValidationError):
            make_payload(content="a" * 2001)

    def test_unknown_topic_rejected(self):
        with pytest.raises(ValidationError):
            InquiryCreate(email="fan@example.com", topic="refunds", content=CONTENT)

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            make_payload(email="not-an-email")
