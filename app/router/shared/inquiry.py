from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_or_ip_key
from app.db.models.identity import Users
from app.deps.auth import get_current_user_optional
from app.deps.db import get_db
from app.schema.shared import InquiryCreate, InquiryCreated, InstantAnswerRead, InstantAnswerRequest
from app.services.shared.faq_answer_service import FaqAnswerService
from app.services.shared.inquiry_service import InquiryService

# Contact form (お問い合わせ). Open to guests; a logged-in sender is linked to their account.
router = APIRouter(prefix="/inquiries", tags=["Inquiries"])

# 3 per 10 minutes: each accepted submission can send an email.
@router.post("/submit", response_model=InquiryCreated)
def submit_inquiry(data: InquiryCreate, current_user: Users | None = Depends(get_current_user_optional), _: None = Depends(rate_limit(3, 600, user_or_ip_key)), db: Session = Depends(get_db)) -> InquiryCreated:
    inquiry = InquiryService.submit_inquiry(db, data, current_user)
    return InquiryCreated(id=inquiry.id, msg="Your inquiry has been received")

# AI answer from the FAQ, shown before the user submits the form. Nothing is saved.
# current_user is only there so the rate limiter can key logged-in users by account.
# 5 per 10 minutes: every call costs money.
@router.post("/instant-answer", response_model=InstantAnswerRead)
def get_instant_answer(data: InstantAnswerRequest, current_user: Users | None = Depends(get_current_user_optional), _: None = Depends(rate_limit(5, 600, user_or_ip_key))) -> InstantAnswerRead:
    return FaqAnswerService.answer(data)
