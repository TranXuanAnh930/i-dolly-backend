import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base

campaign_status_enum = Enum("open", "drawn", "completed", "cancelled", name="campaign_status_enum")


class LotteryCampaign(Base):

    __tablename__ = "lottery_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    ticket_type_id = Column(UUID(as_uuid=True), ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    entry_start_at = Column(DateTime(timezone=True), nullable=False)
    entry_end_at = Column(DateTime(timezone=True), nullable=False)
    # Nullable — NULL means "not drawn yet." Only the draw job itself
    # writes this (app/services/lottery_draw_service.py), never a client;
    # it records when the campaign WAS drawn, not a scheduled target.
    draw_at = Column(DateTime(timezone=True), nullable=True)
    payment_deadline_hours = Column(Integer, nullable=False, server_default="48")
    status = Column(campaign_status_enum, nullable=False, server_default="open")
    # Per-campaign, data-driven cap — raise it for a specific campaign via an
    # UPDATE, no migration needed (database-design.md's note on this table).
    max_entries_per_user = Column(Integer, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("entry_end_at > entry_start_at AND (draw_at IS NULL OR draw_at >= entry_end_at)", name="chk_lottery_campaigns_window"),
        CheckConstraint("payment_deadline_hours > 0", name="chk_lottery_campaigns_deadline_positive"),
        CheckConstraint("max_entries_per_user > 0", name="chk_lottery_campaigns_max_entries_positive"),
    )

    ticket_type = relationship("TicketType")
