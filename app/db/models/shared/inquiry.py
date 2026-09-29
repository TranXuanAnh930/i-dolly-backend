import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.schema.shared.inquiry import InquiryTopic


class Inquiry(Base):

    __tablename__ = "inquiries"
    # Serves the "confirmations sent to this address recently" count.
    __table_args__ = (Index("ix_inquiries_email_created_at", "email", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    email = Column(String, nullable=False)
    topic = Column(Enum(InquiryTopic, name="inquiry_topic_enum"), nullable=False)
    content = Column(Text, nullable=False)
    # Set when the sender was logged in; guests can submit too.
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("Users")
