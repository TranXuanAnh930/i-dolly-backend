import uuid
from sqlalchemy import String, Column, DateTime, ForeignKey, Date, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Group(Base):

    __tablename__ = "groups"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("management_companies.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    debut_date = Column(Date, nullable=True)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, server_default=func.true(), nullable=False)  # soft-delete flag: deactivate instead of hard-delete, see database-design.md §3.3
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False)

    company = relationship("ManagementCompany", back_populates="groups")
    idols = relationship("Idol", back_populates="group")
