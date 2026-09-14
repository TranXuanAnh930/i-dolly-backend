import uuid

from sqlalchemy.orm import Session

from app.db.models.identity.user import Users
from app.db.models.marketplace.album_detail import AlbumDetail
from app.db.models.marketplace.genre import AlbumGenre, Genre
from app.db.models.talent.group import Group
from app.db.models.talent.idol import Idol
from app.schema.marketplace.genre import AlbumGenreAssign, GenreCreate

# genres: a global lookup table, not company-scoped — same rationale as
# idol_colors/positions (manager/admin-extensible without a migration).
# Already seeded (K-Pop, Pop, Dance, ... — schema.sql), so no need to
# re-seed via these endpoints.

def add_genre(db: Session, data: GenreCreate):
    db_genre = Genre(**data.model_dump())
    db.add(db_genre)
    db.commit()
    db.refresh(db_genre)
    return db_genre

def get_genres(db: Session):
    result = db.query(Genre).all()
    if not result:
        return False
    return result

def delete_genre(db: Session, id: uuid.UUID):
    db_genre = db.get(Genre, id)
    if not db_genre:
        return False
    db.delete(db_genre)
    db.commit()
    return True


# --- album_genres (join table) — scoped via the parent album_details row's
# idol/group company, same pattern as album_detail_service.

def _manager_scope_violation(current_user: Users, company_id: uuid.UUID) -> bool:
    return current_user.role == "manager" and current_user.company_id != company_id

def _company_id_for_album(db: Session, product_id: uuid.UUID):
    album = db.get(AlbumDetail, product_id)
    if not album:
        return None, None
    if album.idol_id is not None:
        idol = db.get(Idol, album.idol_id)
        return album, (idol.company_id if idol else None)
    group = db.get(Group, album.group_id)
    return album, (group.company_id if group else None)

def assign_genre(db: Session, data: AlbumGenreAssign, current_user: Users):
    album, company_id = _company_id_for_album(db, data.product_id)
    if not album:
        return "not_found"
    if not db.get(Genre, data.genre_id):
        return "not_found"
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    if db.get(AlbumGenre, (data.product_id, data.genre_id)):
        return "conflict"
    db_link = AlbumGenre(product_id=data.product_id, genre_id=data.genre_id)
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link

def get_album_genres(db: Session, product_id: uuid.UUID):
    result = db.query(AlbumGenre).filter(AlbumGenre.product_id == product_id).all()
    if not result:
        return False
    return result

def get_all_album_genres(db: Session):
    result = db.query(AlbumGenre).all()
    if not result:
        return False
    return result

def remove_genre(db: Session, product_id: uuid.UUID, genre_id: uuid.UUID, current_user: Users):
    link = db.get(AlbumGenre, (product_id, genre_id))
    if not link:
        return "not_found"
    _, company_id = _company_id_for_album(db, product_id)
    if _manager_scope_violation(current_user, company_id):
        return "forbidden"
    db.delete(link)
    db.commit()
    return True
