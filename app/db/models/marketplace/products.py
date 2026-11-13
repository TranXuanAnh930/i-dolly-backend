import uuid

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Product(Base):

    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, index= True, default=uuid.uuid4)
    name = Column(String)
    price = Column(Float)
    description = Column(String)
    quantity = Column(Integer)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id", onupdate="CASCADE", ondelete="RESTRICT"), nullable=False)
    image_url = Column(String, nullable=True)  # local path or S3/CDN URL
    is_active = Column(Boolean, server_default=func.true(), nullable=False)  # soft-delete flag

    cart_items = relationship("Cart", back_populates="product")
    category = relationship("Category", back_populates="products")
    order_items = relationship("OrderItem", back_populates="order_product")
