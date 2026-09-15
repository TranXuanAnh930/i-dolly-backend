import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.deps.auth import require_admin
from app.deps.db import get_db
from app.schema.marketplace import CategoryBase, CategoryRead, CategoryUpdate
from app.services.marketplace.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["Category"])

@router.post("/add")
async def add_new_category(category:CategoryBase, db:Session=Depends(get_db), current_user:Users = Depends(require_admin)):
    db_category = CategoryService.add_categories(db, category)
    if not db_category:
        raise HTTPException(status_code=400, detail="Invalid input")
    return {"msg" : "Category added successfully"}

@router.get("/all", response_model=List[CategoryRead])
async def see_categories(_:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)):
    result = CategoryService.get_categories(db)
    if not result:
        raise HTTPException(status_code=404, detail="No categories found")
    return result

@router.put("/update")
async def update_existing_category(new_category:CategoryUpdate, id:uuid.UUID, db:Session=Depends(get_db), current_user:Users=Depends(require_admin)):
    db_category = CategoryService.update_category(db, id, new_category)
    if not db_category:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"msg" : "Category updated successfully"}

@router.delete("/delete/{id}")
async def delete_existing_category(id:uuid.UUID, db:Session=Depends(get_db), current_user:Users=Depends(require_admin)):
    result = CategoryService.delete_category(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Category not found")    
    return {"msg" : "Category deleted successfully"}