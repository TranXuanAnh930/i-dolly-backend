import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.deps.auth import require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.schema.talent import IdolColorBase, IdolColorCreate, IdolColorRead
from app.services.talent.idol_color_service import IdolColorService

# A lookup table, not an enum, specifically so it's manager/admin-extensible
# without a migration (database-design.md §3.5) — create/update use
# require_manager_or_admin. Delete stays admin-only: colors are global, not
# scoped to one company, so removing one can affect another company's idols;
# a manager shouldn't be able to break another company's data.
router = APIRouter(prefix="/idol_colors", tags=["Idol Colors"])

@router.post("/add", response_model=IdolColorRead)
async def add_new_idol_color(color: IdolColorCreate, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    db_color = IdolColorService.add_idol_color(db, color)
    if not db_color:
        raise HTTPException(status_code=400, detail="Invalid input")
    return db_color

@router.get("/all", response_model=List[IdolColorRead])
async def list_idol_colors(_: None = Depends(rate_limit(10, 60, ip_key)), db: Session = Depends(get_db)):
    result = IdolColorService.get_idol_colors(db)
    if not result:
        raise HTTPException(status_code=404, detail="No idol colors found")
    return result

@router.put("/update/{id}", response_model=IdolColorRead)
async def update_existing_idol_color(id: uuid.UUID, data: IdolColorBase, current_user: Users = Depends(require_manager_or_admin), db: Session = Depends(get_db)):
    db_color = IdolColorService.update_idol_color(db, id, data)
    if not db_color:
        raise HTTPException(status_code=404, detail="Idol color not found")
    return db_color

@router.delete("/delete/{id}")
async def delete_existing_idol_color(id: uuid.UUID, current_user: Users = Depends(require_admin), db: Session = Depends(get_db)):
    result = IdolColorService.delete_idol_color(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Idol color not found")
    return {"msg": "Idol color deleted successfully"}
