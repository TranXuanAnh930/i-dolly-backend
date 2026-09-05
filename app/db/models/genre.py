from sqlalchemy import Integer, Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class Genre(Base):

    __tablename__ = "genres"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)

    albums = relationship("AlbumGenre", back_populates="genre")


class AlbumGenre(Base):

    __tablename__ = "album_genres"

    product_id = Column(Integer, ForeignKey("album_details.product_id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)
    genre_id = Column(Integer, ForeignKey("genres.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True, index=True)

    album = relationship("AlbumDetail", back_populates="genres")
    genre = relationship("Genre", back_populates="albums")
