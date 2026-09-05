from sqlalchemy import String, Integer, Column, DateTime, func
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class ManagementCompany(Base):

    __tablename__ = "management_companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    staff = relationship("Users", back_populates="company")
    groups = relationship("Group", back_populates="company")
    idols = relationship("Idol", back_populates="company")
    concerts = relationship("Concert", back_populates="company")
