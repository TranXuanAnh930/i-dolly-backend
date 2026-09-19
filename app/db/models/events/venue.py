import uuid

from sqlalchemy import Column, Computed, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Venue(Base):

    __tablename__ = "venues"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    city = Column(String, nullable=False)
    country = Column(String, nullable=False)
    total_capacity = Column(Integer, nullable=False)
    # GENERATED ALWAYS AS ... STORED in Postgres (database-design.md §3.7) — Computed() marks it
    # server-derived so SQLAlchemy leaves it out of every INSERT/UPDATE. Plain VARCHAR, not a
    # Postgres enum: a GENERATED STORED expression must be IMMUTABLE, and the enum text->enum cast
    # is only STABLE (enum values can change at runtime via ALTER TYPE ... ADD VALUE).
    size = Column(
        String,
        Computed(
            "CASE WHEN total_capacity < 10000 THEN 'small' "
            "WHEN total_capacity < 20000 THEN 'medium' "
            "WHEN total_capacity < 50000 THEN 'large' "
            "ELSE 'stadium' END"
        ),
        nullable=True,
    )
    contact_info = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    concerts = relationship("Concert", back_populates="venue")
