from sqlalchemy import Integer, Column, DateTime, ForeignKey, SmallInteger, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class LotteryPreference(Base):

    __tablename__ = "lottery_preferences"

    id = Column(Integer, primary_key=True, index=True)
    concert_id = Column(Integer, ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    ticket_type_id = Column(Integer, ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
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
