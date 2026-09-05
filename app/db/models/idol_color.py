from sqlalchemy import String, Integer, Column, CheckConstraint
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class IdolColor(Base):

    __tablename__ = "idol_colors"
    __table_args__ = (
        CheckConstraint("hex_code ~ '^#[0-9A-Fa-f]{6}$'", name="chk_idol_colors_hex_format"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    hex_code = Column(String(7), nullable=False, unique=True)

    idols = relationship("Idol", back_populates="color")
