from fastapi import HTTPException, Depends, APIRouter
from typing import List
from app.cache.rate_limit import ip_key, rate_limit
from app.schema.category import CategoryBase, CategoryUpdate, CategoryRead
from sqlalchemy.orm import Session
from app.deps.auth import require_admin
from app.deps.db import get_db
from app.db.models.user import Users
from app.services.category_service import add_categories, get_categories, update_category, delete_category

router = APIRouter(prefix="/Categories", tags=["Category"])

@router.post("/add")
async def add_new_category(category:CategoryBase, db:Session=Depends(get_db), current_user:Users = Depends(require_admin)):
    db_category = add_categories(db, category)
    if not db_category:
        raise HTTPException(status_code=400, detail="Invalid input")
    return {"msg" : "Category added successfully"}

@router.get("/all", response_model=List[CategoryRead])
async def see_categories(_:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)):
    result = get_categories(db)
    if not result:
        raise HTTPException(status_code=404, detail="No categories found")
    return result

@router.put("/update")
async def update_existing_category(new_category:CategoryUpdate, id:int, db:Session=Depends(get_db), current_user:Users=Depends(require_admin)):
    db_category = update_category(db, id, new_category)
    if not db_category:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"msg" : "Category updated successfully"}

@router.delete("/delete/{id}")
async def delete_existing_category(id:int, db:Session=Depends(get_db), current_user:Users=Depends(require_admin)):
    result = delete_category(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Category not found")    
    return {"msg" : "Category deleted successfully"}