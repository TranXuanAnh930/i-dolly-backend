import uuid

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.schema.marketplace.order import OrderStatus


class Order(Base):

    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    shipping_address_id = Column(UUID(as_uuid=True), ForeignKey("shipping_addresses.id", ondelete="CASCADE"), nullable=False)
    total_price = Column(Float, nullable=False)
    status = Column(Enum(OrderStatus, name="order_status_enum"), default=OrderStatus.pending)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items = relationship("OrderItem", back_populates="order")
    user_item = relationship("Users", back_populates="user_order")
    shippingaddress = relationship("ShippingAddress", back_populates="orders")
    shippingstatus = relationship("ShippingStatus", back_populates="orderid", uselist=False)
    payment = relationship("Payment", back_populates="order_payment")

class OrderItem(Base):

    __tablename__ = "orders_items"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
    order_product = relationship("Product", back_populates="order_items")