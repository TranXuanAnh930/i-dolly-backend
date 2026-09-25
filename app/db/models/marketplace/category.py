import uuid

from sqlalchemy import Boolean, Column, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Category(Base):

    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    is_resale_capped = Column(Boolean, nullable=False, server_default=func.true())  # applies RESALE_CAP_QUANTITY to this category's products

    products = relationship("Product", back_populates="category")