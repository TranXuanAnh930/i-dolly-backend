import uuid
from app.db.base_class import Base
from sqlalchemy import Column, Integer, ForeignKey, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

class Cart(Base):

    __tablename__ = "cart"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, server_default="1", nullable=False)
    price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
    
    product = relationship("Product", back_populates="cart_items")
    user  = relationship("Users", back_populates="cart")

    __table_args__ = (
        UniqueConstraint('user_id', 'product_id', name='uq_cart_user_id_product_id'),
    )