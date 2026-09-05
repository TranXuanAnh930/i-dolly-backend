from sqlalchemy import String, Integer, Column, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Position(Base):

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)

    idol_positions = relationship("IdolPosition", back_populates="position")


class IdolPosition(Base):

    __tablename__ = "idol_positions"

    idol_id = Column(Integer, ForeignKey("idols.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)
    position_id = Column(Integer, ForeignKey("positions.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)
    is_primary = Column(Boolean, nullable=False, server_default="false")

    idol = relationship("Idol", back_populates="idol_positions")
    position = relationship("Position", back_populates="idol_positions")
