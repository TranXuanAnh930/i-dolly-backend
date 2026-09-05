from fastapi import HTTPException, Depends, APIRouter
from typing import List
from sqlalchemy.orm import Session
from app.deps.auth import require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.genre import GenreCreate, GenreRead, AlbumGenreAssign, AlbumGenreRead
from app.services.genre_service import (
    add_genre, get_genres, delete_genre,
    assign_genre, get_album_genres, remove_genre,
)

# Same rationale as idol_colors/positions: a lookup table, manager/admin-
# extensible without a migration. Delete stays admin-only (cross-company
# impact — removing a genre affects every album tagged with it, regardless
# of company).
router = APIRouter(prefix="/genres", tags=["Genres"])

@router.post("/add", response_model=GenreRead)
async def add_new_genre(genre: GenreCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    return add_genre(db, genre)

@router.get("/all", response_model=List[GenreRead])
async def list_genres(db: Session = Depends(get_db)):
    result = get_genres(db)
    if not result:
        raise HTTPException(status_code=404, detail="No genres found")
    return result

@router.delete("/delete/{id}")
async def delete_existing_genre(id: int, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    result = delete_genre(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Genre not found")
    return {"msg": "Genre deleted successfully"}


# --- album_genres (join table) — nested under /genres/album_genres, scoped
# via the parent album_details row's idol/group company (genre_service).

def _raise_for_link(result):
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only tag albums belonging to their own company's idols/groups")
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Album details or genre not found")
    if result == "conflict":
        raise HTTPException(status_code=400, detail="This album is already tagged with this genre")

@router.post("/album_genres/assign", response_model=AlbumGenreRead)
async def assign_genre_to_album(data: AlbumGenreAssign, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = assign_genre(db, data, current_user)
    if isinstance(result, str):
        _raise_for_link(result)
    return result

@router.get("/album_genres/album/{product_id}", response_model=List[AlbumGenreRead])
async def list_album_genres(product_id: int, db: Session = Depends(get_db)):
    result = get_album_genres(db, product_id)
    if not result:
        raise HTTPException(status_code=404, detail="This album has no genres tagged")
    return result

@router.delete("/album_genres/{product_id}/{genre_id}")
async def unassign_genre_from_album(product_id: int, genre_id: int, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    result = remove_genre(db, product_id, genre_id, current_user)
    if isinstance(result, str):
        _raise_for_link(result)
    return {"msg": "Genre unassigned from album successfully"}
