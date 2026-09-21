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

# Same rationale as idol_colors/positions: a lookup table, manager/admin-
# extensible without a migration. Delete stays admin-only (cross-company
# impact — removing a genre affects every album tagged with it, regardless
# of company).
router = APIRouter(prefix="/genres", tags=["Genres"])

# FRONTEND: not currently called by i-dolly-frontend. No service class for
# this entity exists there at all — the whole /genres router is unused.
@router.post("/add", response_model=GenreRead)
async def add_new_genre(genre: GenreCreate, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> Genre:
    return GenreService.add_genre(db, genre)

# FRONTEND: not currently called by i-dolly-frontend.
@router.get("/all", response_model=List[GenreRead])
async def list_genres(db: Session = Depends(get_db)) -> list[Genre]:
    result = GenreService.get_genres(db)
    if not result:
        raise HTTPException(status_code=404, detail="No genres found")
    return result

# FRONTEND: not currently called by i-dolly-frontend.
@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_genre(id: uuid.UUID, current_user: Users = Depends(require_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    result = GenreService.delete_genre(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Genre not found")
    return MessageResponse(msg="Genre deleted successfully")


# --- album_genres (join table) — nested under /genres/album_genres, scoped
# via the parent album_details row's idol/group company (genre_service).

# FRONTEND: not currently called by i-dolly-frontend. A product's genre
# tags show up in the UI (ProductDetailPage, ReleaseCard) only as data
# already embedded in the store-page/detail bundles — this join-table CRUD
# itself is unused.
@router.post("/album_genres/assign", response_model=AlbumGenreRead)
async def assign_genre_to_album(data: AlbumGenreAssign, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> AlbumGenre:
    try:
        return GenreService.assign_genre(db, data, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# FRONTEND: not currently called by i-dolly-frontend.
@router.get("/album_genres/album/{product_id}", response_model=List[AlbumGenreRead])
async def list_album_genres(product_id: uuid.UUID, db: Session = Depends(get_db)) -> list[AlbumGenre]:
    result = GenreService.get_album_genres(db, product_id)
    if not result:
        raise HTTPException(status_code=404, detail="This album has no genres tagged")
    return result

# Bulk read — lets a client building a store grid (or any other view needing
# every album's genre tags) fetch them in one request instead of one per
# product.
# FRONTEND: not currently called by i-dolly-frontend.
@router.get("/album_genres/all", response_model=List[AlbumGenreRead])
async def list_all_album_genres(db: Session = Depends(get_db)) -> list[AlbumGenre]:
    result = GenreService.get_all_album_genres(db)
    if not result:
        raise HTTPException(status_code=404, detail="No album genres found")
    return result

# FRONTEND: not currently called by i-dolly-frontend.
@router.delete("/album_genres/{product_id}/{genre_id}", response_model=MessageResponse)
async def unassign_genre_from_album(product_id: uuid.UUID, genre_id: uuid.UUID, current_user: Users = Depends(require_manager_or_admin), _: None = Depends(rate_limit(20, 60, user_key)), db: Session = Depends(get_db)) -> MessageResponse:
    try:
        GenreService.remove_genre(db, product_id, genre_id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return MessageResponse(msg="Genre unassigned from album successfully")
