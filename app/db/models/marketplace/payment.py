import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.schema.marketplace import PaymentGateway, PaymentStatus


class Payment(Base):

    __tablename__ = "payment"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    # Exactly one of order_id/ticket_id is set, depending on which checkout created the payment.
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
    # PayPal's buyer approval link; null for mock payments.
    pg_approval_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False)
    # Unique per checkout attempt, so a retried request can't create a second payment.
    idempotency_key = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)

    order_payment = relationship("Order", back_populates="payment")
    ticket_payment = relationship("Ticket", foreign_keys=[ticket_id])
    user_payment = relationship("Users", back_populates="paymentuser")