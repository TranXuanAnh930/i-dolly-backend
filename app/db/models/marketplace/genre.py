import uuid

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Genre(Base):

    __tablename__ = "genres"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)

    albums = relationship("AlbumGenre", back_populates="genre")


class AlbumGenre(Base):

    __tablename__ = "album_genres"

    product_id = Column(UUID(as_uuid=True), ForeignKey("album_details.product_id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)
    genre_id = Column(UUID(as_uuid=True), ForeignKey("genres.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True, index=True)

    album = relationship("AlbumDetail", back_populates="genres")
    genre = relationship("Genre", back_populates="albums")
