import uuid
from sqlalchemy import Column, DateTime, ForeignKey, SmallInteger, UniqueConstraint, CheckConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class LotteryPreference(Base):

    __tablename__ = "lottery_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    concert_id = Column(UUID(as_uuid=True), ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    ticket_type_id = Column(UUID(as_uuid=True), ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    rank = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("concert_id", "user_id", "rank", name="uq_lottery_preferences_rank"),
        UniqueConstraint("concert_id", "user_id", "ticket_type_id", name="uq_lottery_preferences_tier"),
        CheckConstraint("rank > 0", name="chk_lottery_preferences_rank_positive"),
    )

    concert = relationship("Concert")
    user = relationship("Users")
    ticket_type = relationship("TicketType")
