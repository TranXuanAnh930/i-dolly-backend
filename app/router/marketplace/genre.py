import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity import Users
from app.db.models.marketplace import AlbumGenre, Genre
from app.deps.auth import require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.marketplace import AlbumGenreAssign, AlbumGenreRead, GenreCreate, GenreRead
from app.services.marketplace.genre_service import GenreService

# Lookup table managers/admins can extend; delete is admin-only since genres are shared across
# companies.
router = APIRouter(prefix="/genres", tags=["Genres"])

# Not used by the frontend (nor is the rest of this router).
@router.post("/add", response_model=GenreRead)
def add_new_genre(genre: GenreCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> Genre:
    return GenreService.add_genre(db, genre)

# Not used by the frontend.
@router.get("/all", response_model=List[GenreRead])
def list_genres(db: Session = Depends(get_db)) -> list[Genre]:
    result = GenreService.get_genres(db)
    if not result:
        raise HTTPException(status_code=404, detail="No genres found")
    return result

# Not used by the frontend.
@router.delete("/delete/{id}", response_model=MessageResponse)
def delete_existing_genre(id: uuid.UUID, current_user: Users = Depends(require_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    result = GenreService.delete_genre(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Genre not found")
    return MessageResponse(msg="Genre deleted successfully")


# --- album_genres (join table), scoped by the album's idol/group company.

# Not used by the frontend.
@router.post("/album_genres/assign", response_model=AlbumGenreRead)
def assign_genre_to_album(data: AlbumGenreAssign, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> AlbumGenre:
    try:
        return GenreService.assign_genre(db, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# Not used by the frontend.
@router.get("/album_genres/album/{product_id}", response_model=List[AlbumGenreRead])
def list_album_genres(product_id: uuid.UUID, db: Session = Depends(get_db)) -> list[AlbumGenre]:
    result = GenreService.get_album_genres(db, product_id)
    if not result:
        raise HTTPException(status_code=404, detail="This album has no genres tagged")
    return result

# Every album's genre tags in one request.
# Not used by the frontend.
@router.get("/album_genres/all", response_model=List[AlbumGenreRead])
def list_all_album_genres(db: Session = Depends(get_db)) -> list[AlbumGenre]:
    result = GenreService.get_all_album_genres(db)
    if not result:
        raise HTTPException(status_code=404, detail="No album genres found")
    return result

# Not used by the frontend.
@router.delete("/album_genres/{product_id}/{genre_id}", response_model=MessageResponse)
def unassign_genre_from_album(product_id: uuid.UUID, genre_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        GenreService.remove_genre(db, product_id, genre_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return MessageResponse(msg="Genre unassigned from album successfully")
