import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models.identity import Users
from app.db.models.marketplace import AlbumDetail, AlbumGenre, Genre
from app.db.models.talent import Group, Idol
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.schema.marketplace import AlbumGenreAssign, GenreCreate


class GenreService:

    # genres: a global lookup table, not company-scoped — same rationale as
    # idol_colors/positions (manager/admin-extensible without a migration).
    # Already seeded (K-Pop, Pop, Dance, ... — schema.sql), so no need to
    # re-seed via these endpoints.

    @staticmethod
    def add_genre(db: Session, data: GenreCreate) -> Genre:
        db_genre = Genre(**data.model_dump())
        db.add(db_genre)
        db.commit()
        db.refresh(db_genre)
        return db_genre

    @staticmethod
    def get_genres(db: Session) -> list[Genre] | Literal[False]:
        result = db.query(Genre).all()
        if not result:
            return False
        return result

    @staticmethod
    def delete_genre(db: Session, id: uuid.UUID) -> bool:
        db_genre = db.get(Genre, id)
        if not db_genre:
            return False
        db.delete(db_genre)
        db.commit()
        return True

    # --- album_genres (join table) — scoped via the parent album_details row's
    # idol/group company, same pattern as album_detail_service.

    @staticmethod
    def _manager_scope_violation(current_user: Users, company_id: uuid.UUID | None) -> bool:
        return current_user.role == "manager" and current_user.company_id != company_id

    @staticmethod
    def _company_id_for_album(db: Session, product_id: uuid.UUID) -> tuple[AlbumDetail | None, uuid.UUID | None]:
        album = db.get(AlbumDetail, product_id)
        if not album:
            return None, None
        if album.idol_id is not None:
            idol = db.get(Idol, album.idol_id)
            return album, (idol.company_id if idol else None)
        group = db.get(Group, album.group_id)
        return album, (group.company_id if group else None)

    @staticmethod
    def assign_genre(db: Session, data: AlbumGenreAssign, current_user: Users) -> AlbumGenre:
        album, company_id = GenreService._company_id_for_album(db, data.product_id)
        if not album:
            raise NotFoundError("Album details or genre not found")
        if not db.get(Genre, data.genre_id):
            raise NotFoundError("Album details or genre not found")
        if GenreService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only tag albums belonging to their own company's idols/groups")
        if db.get(AlbumGenre, (data.product_id, data.genre_id)):
            raise BadRequestError("This album is already tagged with this genre")
        db_link = AlbumGenre(product_id=data.product_id, genre_id=data.genre_id)
        db.add(db_link)
        db.commit()
        db.refresh(db_link)
        return db_link

    @staticmethod
    def get_album_genres(db: Session, product_id: uuid.UUID) -> list[AlbumGenre] | Literal[False]:
        result = db.query(AlbumGenre).filter(AlbumGenre.product_id == product_id).all()
        if not result:
            return False
        return result

    @staticmethod
    def get_all_album_genres(db: Session) -> list[AlbumGenre] | Literal[False]:
        result = db.query(AlbumGenre).all()
        if not result:
            return False
        return result

    @staticmethod
    def remove_genre(db: Session, product_id: uuid.UUID, genre_id: uuid.UUID, current_user: Users) -> Literal[True]:
        link = db.get(AlbumGenre, (product_id, genre_id))
        if not link:
            raise NotFoundError("Album details or genre not found")
        _, company_id = GenreService._company_id_for_album(db, product_id)
        if GenreService._manager_scope_violation(current_user, company_id):
            raise ForbiddenError("Managers can only tag albums belonging to their own company's idols/groups")
        db.delete(link)
        db.commit()
        return True
