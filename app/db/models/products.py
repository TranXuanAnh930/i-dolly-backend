from sqlalchemy import Column, Integer, Float, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Product(Base):
   
    __tablename__ = "products"
   
    id = Column(Integer, primary_key=True, index= True)
    name = Column(String)
    price = Column(Float)
    description = Column(String)
    quantity = Column(Integer)
    category_id = Column(Integer, ForeignKey("categories.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    image_url = Column(String, nullable=True)  # local path or S3/CDN URL — see app/utils/storage.py

    cart_items = relationship("Cart", back_populates="product")
    category = relationship("Category", back_populates="products")
    order_items = relationship("OrderItem", back_populates="order_product")
