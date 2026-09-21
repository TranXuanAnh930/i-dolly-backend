import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.schema.events.ticket_type import SaleMethod, TicketTier


class TicketType(Base):

    __tablename__ = "ticket_types"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    concert_id = Column(UUID(as_uuid=True), ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    tier = Column(Enum(TicketTier, name="ticket_tier_enum"), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    total_quantity = Column(Integer, nullable=False)
    sold_quantity = Column(Integer, nullable=False, server_default="0")
    sale_method = Column(Enum(SaleMethod, name="sale_method_enum"), nullable=False, server_default="lottery")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("concert_id", "tier", "sale_method", name="uq_ticket_types_concert_tier_method"),
        CheckConstraint("sold_quantity <= total_quantity", name="chk_ticket_types_capacity"),
    )

    concert = relationship("Concert", back_populates="ticket_types")
