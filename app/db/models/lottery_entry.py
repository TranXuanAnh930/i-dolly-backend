import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

lottery_entry_status_enum = Enum("pending", "won", "lost", "expired", name="lottery_entry_status_enum")


class LotteryEntry(Base):

    __tablename__ = "lottery_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("lottery_campaigns.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(lottery_entry_status_enum, nullable=False, server_default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    drawn_at = Column(DateTime(timezone=True), nullable=True)
    # NOTE: no UNIQUE(campaign_id, user_id) — the cap lives on
    # lottery_campaigns.max_entries_per_user, enforced by a DB trigger
    # (trg_lottery_entries_cap) and mirrored in lottery_entry_service for a
    # clean 400 instead of a raw IntegrityError.

    campaign = relationship("LotteryCampaign")
    user = relationship("Users")
