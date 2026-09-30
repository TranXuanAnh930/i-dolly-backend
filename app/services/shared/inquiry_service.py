from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db.models.identity import Users
from app.db.models.shared import Inquiry
from app.schema.shared import InquiryCreate
from app.utils.email_templates import EmailTemplate

# The email goes to whatever address was typed, so cap how many one address can receive.
CONFIRMATIONS_PER_ADDRESS = 3
CONFIRMATION_WINDOW = timedelta(hours=1)


class InquiryService:

    @staticmethod
    def submit_inquiry(db: Session, data: InquiryCreate, current_user: Users | None) -> Inquiry:
        """Save the inquiry, then email a confirmation unless this address has already received
        CONFIRMATIONS_PER_ADDRESS of them within CONFIRMATION_WINDOW. Over the cap, the inquiry
        is still saved; only the email is skipped."""
        # Lowercased so changing letter case can't get around the per-address cap.
        email = data.email.lower()

        # Counted before the insert, so this inquiry isn't part of its own total.
        since = datetime.now(timezone.utc) - CONFIRMATION_WINDOW
        recent = db.query(Inquiry).filter(Inquiry.email == email, Inquiry.created_at >= since).count()

        inquiry = Inquiry(
            email=email,
            topic=data.topic,
            content=data.content,
            user_id=current_user.id if current_user else None,
        )
        db.add(inquiry)
        db.commit()
        db.refresh(inquiry)

        if recent < CONFIRMATIONS_PER_ADDRESS:
            email_body = EmailTemplate.INQUIRY_RECEIVED.render(
                email=email, inquiry_id=inquiry.id, topic=data.topic.label
            )
            celery_app.send_task(
                "app.tasks.email.send_email",
                args=[email, EmailTemplate.INQUIRY_RECEIVED.subject, email_body],
            )
        return inquiry
