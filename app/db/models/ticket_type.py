from sqlalchemy import String, Integer, Column, DateTime, ForeignKey, Enum, Numeric, CheckConstraint, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.db.base_class import Base

ticket_tier_enum = Enum("vip", "premium", "regular", name="ticket_tier_enum")
sale_method_enum = Enum("lottery", "direct", name="sale_method_enum")


class TicketType(Base):

    __tablename__ = "ticket_types"

    id = Column(Integer, primary_key=True, index=True)
    concert_id = Column(Integer, ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    tier = Column(ticket_tier_enum, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    total_quantity = Column(Integer, nullable=False)
    sold_quantity = Column(Integer, nullable=False, server_default="0")
    sale_method = Column(sale_method_enum, nullable=False, server_default="lottery")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("concert_id", "tier", "sale_method", name="uq_ticket_types_concert_tier_method"),
        CheckConstraint("sold_quantity <= total_quantity", name="chk_ticket_types_capacity"),
    )

    concert = relationship("Concert", back_populates="ticket_types")
