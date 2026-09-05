import uuid
from sqlalchemy import String, Integer, Column, DateTime, ForeignKey, Text, Enum, CheckConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

concert_status_enum = Enum(
    "scheduled", "on_sale", "sold_out", "completed", "cancelled", name="concert_status_enum"
)


class Concert(Base):

    __tablename__ = "concerts"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("management_companies.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    venue_id = Column(UUID(as_uuid=True), ForeignKey("venues.id", onupdate="CASCADE", ondelete="RESTRICT"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    capacity = Column(Integer, nullable=False)  # may be <= venue.total_capacity; not DB-enforced (database-design.md §3.7)
    event_datetime = Column(DateTime(timezone=True), nullable=False)
    doors_open_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(concert_status_enum, nullable=False, server_default="scheduled")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False)

    company = relationship("ManagementCompany", back_populates="concerts")
    venue = relationship("Venue", back_populates="concerts")
    performers = relationship("ConcertPerformer", back_populates="concert")
    ticket_types = relationship("TicketType", back_populates="concert")


class ConcertPerformer(Base):

    __tablename__ = "concert_performers"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    concert_id = Column(UUID(as_uuid=True), ForeignKey("concerts.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    idol_id = Column(UUID(as_uuid=True), ForeignKey("idols.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=True)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=True)

    concert = relationship("Concert", back_populates="performers")
    idol = relationship("Idol")
    group = relationship("Group")
