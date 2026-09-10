import uuid
from sqlalchemy import String, Column, DateTime, ForeignKey, Date, Text, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Idol(Base):

    __tablename__ = "idols"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("management_companies.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True)  # nullable: solo idols
    name = Column(String, nullable=False)  # single name field; real_name deliberately deferred, see database-design.md §6
    date_of_birth = Column(Date, nullable=True)
    hometown = Column(String, nullable=True)
    color_id = Column(UUID(as_uuid=True), ForeignKey("idol_colors.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True)  # signature/member color
    short_intro = Column(String(500), nullable=True)
    long_description = Column(Text, nullable=True)
    profile_image_url = Column(String, nullable=True)
    is_active = Column(Boolean, server_default=func.true(), nullable=False)  # soft-delete flag: deactivate instead of hard-delete, see database-design.md §3.4
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False)

    company = relationship("ManagementCompany", back_populates="idols")
    group = relationship("Group", back_populates="idols")
    color = relationship("IdolColor", back_populates="idols")
    idol_positions = relationship("IdolPosition", back_populates="idol")
