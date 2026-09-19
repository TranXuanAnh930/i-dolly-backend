import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.schema.events.direct_sale_campaign import DirectSaleCampaignStatus


class DirectSaleCampaign(Base):
    """A time-boxed on-sale window for one direct-sale ticket type — the
    same "campaign defines when it's purchasable" shape lottery_campaigns
    gives lottery tiers, minus the draw step. checkout_ticket only allows a
    purchase while a campaign for that ticket_type is status='open' and
    sale_start_at <= now() <= sale_end_at (ticket_service.checkout_ticket)."""

    __tablename__ = "direct_sale_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    ticket_type_id = Column(UUID(as_uuid=True), ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    sale_start_at = Column(DateTime(timezone=True), nullable=False)
    sale_end_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(DirectSaleCampaignStatus, name="direct_sale_campaign_status_enum"), nullable=False, server_default="open")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("sale_end_at > sale_start_at", name="chk_direct_sale_campaigns_window"),
    )

    ticket_type = relationship("TicketType")
