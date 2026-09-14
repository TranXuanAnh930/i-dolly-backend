import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.schema.shipping import ShippingStatus as SchemaStatus


class ShippingAddress(Base):

    __tablename__ = "shipping_addresses"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    address_line1 = Column(String, nullable=False)
    address_line2 = Column(String,nullable=True)
    city = Column(String, nullable=False)
    postal_code = Column(Integer, nullable=False)
    state = Column(String, nullable=False)
    country = Column(String, nullable=False)

    useradd = relationship("Users", back_populates="shippingadd")
    orders = relationship("Order", back_populates="shippingaddress")

class ShippingStatus(Base):
     
    __tablename__ = "shipping_status"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    status =  Column(Enum(SchemaStatus, name="shipping_status_enum"), default=SchemaStatus.pending)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False)

    orderid = relationship("Order", back_populates="shippingstatus")