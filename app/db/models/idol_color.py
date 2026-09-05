import uuid
from sqlalchemy import String, Column, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class IdolColor(Base):

    __tablename__ = "idol_colors"
    __table_args__ = (
        CheckConstraint("hex_code ~ '^#[0-9A-Fa-f]{6}$'", name="chk_idol_colors_hex_format"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    hex_code = Column(String(7), nullable=False, unique=True)

    idols = relationship("Idol", back_populates="color")
