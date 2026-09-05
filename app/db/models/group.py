from sqlalchemy import String, Integer, Column, DateTime, ForeignKey, Date, func
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Group(Base):

    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("management_companies.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    debut_date = Column(Date, nullable=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False)

    company = relationship("ManagementCompany", back_populates="groups")
    idols = relationship("Idol", back_populates="group")
