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
    # GENERATED ALWAYS AS ... STORED in Postgres (database-design.md §3.7) —
    # Computed() tells SQLAlchemy this column is server-derived, so it's
    # correctly left out of every INSERT/UPDATE this app ever issues. The
    # column and its generation expression already exist from the migration
    # (965f5718222d) via raw DDL; this mirrors that expression for
    # documentation, not to (re-)create it — create_all() is never run
    # against this already-migrated table.
    #
    # CORRECTION: originally typed as a Postgres `venue_size_enum`, cast via
    # `::venue_size_enum` inside the CASE. That broke on a real Postgres
    # instance ("generation expression is not immutable") — a GENERATED
    # STORED expression must be strictly IMMUTABLE, and Postgres's text->enum
    # cast for a user-defined enum goes through `enum_in()`, which is STABLE,
    # not IMMUTABLE (enum membership can change at runtime via ALTER TYPE ...
    # ADD VALUE). Casting to a user-defined enum can never appear inside a
    # GENERATED STORED expression. Fixed by making this a plain String/VARCHAR
    # column instead — see the corrected 965f5718222d migration.
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
