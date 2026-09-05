from sqlalchemy.orm import relationship
from sqlalchemy import String, Integer, Column, Boolean, func
from app.db.base_class import Base

class Category(Base):
    
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    is_resale_capped = Column(Boolean, nullable=False, server_default=func.true())  # data-driven anti-resale flag (database-design.md §4.2) — defaults true, an UPDATE opts a category out

    products = relationship("Product", back_populates="category")