import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.schema.identity.user import UserRole


class Users(Base):

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True,index=True, nullable=False)
    is_active = Column(Boolean, server_default=func.true(), nullable=False)
    is_admin = Column(Boolean, server_default=func.false(), nullable=False)  # deprecated; `role` is authoritative
    role = Column(Enum(UserRole, name="user_role_enum"), nullable=False, server_default="fan")
    company_id = Column(UUID(as_uuid=True), ForeignKey("management_companies.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True)  # managers only; enforced in the service layer
    hashed_password = Column(String, nullable=False)
    is_verified = Column(Boolean, server_default=func.false(), nullable=False)
    created_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        server_onupdate=func.now(), 
        nullable=False
    )

    # passive_deletes: these FKs are NOT NULL with ON DELETE CASCADE, so let Postgres delete the rows
    # instead of SQLAlchemy nulling the FK first.
    cart = relationship("Cart", back_populates="user", passive_deletes=True)
    shippingadd = relationship("ShippingAddress", back_populates="useradd", passive_deletes=True)
    user_order = relationship("Order", back_populates="user_item", passive_deletes=True)
    paymentuser = relationship("Payment", back_populates="user_payment", passive_deletes=True)
    company = relationship("ManagementCompany", back_populates="staff")