import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.schema.events.lottery_entry import LotteryEntryStatus


class LotteryEntry(Base):

    __tablename__ = "lottery_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("lottery_campaigns.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Enum(LotteryEntryStatus, name="lottery_entry_status_enum"), nullable=False, server_default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    drawn_at = Column(DateTime(timezone=True), nullable=True)
    # No UNIQUE(campaign_id, user_id): the per-user cap is max_entries_per_user, enforced by
    # trg_lottery_entries_cap and checked in lottery_entry_service.

    campaign = relationship("LotteryCampaign")
    user = relationship("Users")
