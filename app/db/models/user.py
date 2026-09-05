import uuid
from sqlalchemy import String, Column, DateTime, Boolean, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Users(Base):

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True,index=True, nullable=False)
    is_active = Column(Boolean, server_default=func.true(), nullable=False)
    is_admin = Column(Boolean, server_default=func.false(), nullable=False)  # deprecated, superseded by role — kept until app code no longer reads it (CLAUDE.md Section 5)
    role = Column(Enum("admin", "manager", "fan", name="user_role_enum"), nullable=False, server_default="fan")
    company_id = Column(UUID(as_uuid=True), ForeignKey("management_companies.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True)  # set only when role='manager'; enforced in service layer, not a DB constraint
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

    cart = relationship("Cart", back_populates="user")
    shippingadd = relationship("ShippingAddress", back_populates="useradd")
    user_order = relationship("Order", back_populates="user_item")
    paymentuser = relationship("Payment", back_populates="user_payment")
    company = relationship("ManagementCompany", back_populates="staff")