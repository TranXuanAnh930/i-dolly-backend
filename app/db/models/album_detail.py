from sqlalchemy import Integer, Column, Date, String, ForeignKey, Enum, CheckConstraint
from sqlalchemy.orm import relationship
from app.db.base_class import Base

release_format_enum = Enum("physical", "digital", name="release_format_enum")


class AlbumDetail(Base):

    __tablename__ = "album_details"

    product_id = Column(Integer, ForeignKey("products.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)
    idol_id = Column(Integer, ForeignKey("idols.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True, index=True)
    release_date = Column(Date, nullable=True)
    track_count = Column(Integer, nullable=True)
    format = Column(release_format_enum, nullable=False, server_default="physical")
    cover_image_url = Column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("idol_id IS NOT NULL OR group_id IS NOT NULL", name="chk_album_details_artist"),
        CheckConstraint("track_count IS NULL OR track_count > 0", name="chk_album_details_track_count"),
    )

    product = relationship("Product")
    idol = relationship("Idol")
    group = relationship("Group")
    genres = relationship("AlbumGenre", back_populates="album")
