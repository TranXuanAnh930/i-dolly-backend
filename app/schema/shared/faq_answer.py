from enum import Enum

from pydantic import BaseModel, Field

from app.schema.shared.inquiry import InquiryTopic


class FaqLanguage(str, Enum):
    """Which FAQ file to answer from. The answer itself follows the question's language."""

    en = "en"
    ja = "ja"


class InstantAnswerRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    topic: InquiryTopic
    # 5, not more: a complete Japanese question can be very short (「返金できますか？」 is 8).
    content: str = Field(..., min_length=5, max_length=2000)
    lang: FaqLanguage = FaqLanguage.en


class InstantAnswerRead(BaseModel):
    answerable: bool
    answer: str | None = None


class FaqAnswer(BaseModel):
    """What the model must return (structured output). Not an API response."""

    answerable_from_faq: bool
    answer: str
