import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base

notification_type_enum = Enum(
    "order_confirmation",
    "ticket_confirmation",
    "lottery_registered",
    "lottery_result",
    "lottery_payment_reminder",
    "lottery_payment_confirmation",
    "event_reminder",
    "password_reset",
    name="notification_type_enum",
)
notification_status_enum = Enum("pending", "sent", "failed", name="notification_status_enum")


class Notification(Base):

    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(notification_type_enum, nullable=False)

    # Exactly one of these is expected to be set, depending on `type` — a
    # service-layer check, not a DB constraint (see the migration's docstring).
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=True, index=True)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=True, index=True)
    lottery_entry_id = Column(UUID(as_uuid=True), ForeignKey("lottery_entries.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=True, index=True)
    concert_id = Column(UUID(as_uuid=True), ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=True, index=True)

    status = Column(notification_status_enum, nullable=False, server_default="pending")
    sent_at = Column(DateTime(timezone=True), nullable=True)

    is_read = Column(Boolean, nullable=False, server_default="false")
    read_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("Users")
    order = relationship("Order")
    ticket = relationship("Ticket")
    lottery_entry = relationship("LotteryEntry")
    concert = relationship("Concert")
