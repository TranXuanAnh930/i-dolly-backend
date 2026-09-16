import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base

ticket_status_enum = Enum(
    "reserved", "pending_payment", "paid", "cancelled", "expired", "used", name="ticket_status_enum"
)


class Ticket(Base):

    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    ticket_type_id = Column(UUID(as_uuid=True), ForeignKey("ticket_types.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    lottery_entry_id = Column(UUID(as_uuid=True), ForeignKey("lottery_entries.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True)  # null = directly purchased, no lottery
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payment.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True)
    status = Column(ticket_status_enum, nullable=False, server_default="reserved")
    issued_code = Column(String, unique=True, nullable=True)  # set once status = 'paid'
    reserved_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    payment_deadline_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False)

    ticket_type = relationship("TicketType")
    user = relationship("Users")
    lottery_entry = relationship("LotteryEntry")
    # foreign_keys is required here now — payment.ticket_id (added for
    # Payment -> Ticket traceability, see payment_service.
    # create_ticket_payment) gives this pair of tables a second FK path,
    # which SQLAlchemy can't disambiguate on its own.
    payment = relationship("Payment", foreign_keys=[payment_id])
