import uuid
from app.db.base_class import Base
from app.schema.payment import PaymentStatus, PaymentGateway
from sqlalchemy import Boolean, Column, DateTime, Integer, ForeignKey, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

class Payment(Base):

    __tablename__ = "payment"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    # Exactly one of order_id/ticket_id is set — which checkout flow
    # (order_service.checkout vs ticket_service.checkout_ticket) created
    # this payment. Both nullable, both pointing the same direction (unlike
    # tickets.payment_id, which points from Ticket at this row instead), so
    # a payment can always say what it was *for* without a reverse scan.
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=True)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(Enum(PaymentStatus, name="payment_status_enum"), default=PaymentStatus.pending)
    payment_gateway = Column(Enum(PaymentGateway, name="payment_gateway_enum"), default=PaymentGateway.mock)
    is_paid = Column(Boolean, default=False)
    pg_order_id = Column(String, nullable=True)
    pg_payment_id = Column(String, nullable=True)
    pg_signature = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False)

    order_payment = relationship("Order", back_populates="payment")
    ticket_payment = relationship("Ticket", foreign_keys=[ticket_id])
    user_payment = relationship("Users", back_populates="paymentuser")