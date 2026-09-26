import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.db.models.marketplace import Category
from app.deps.auth import require_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.marketplace import CategoryBase, CategoryRead, CategoryUpdate
from app.services.marketplace.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["Category"])

# Not used by the frontend (nor is the rest of this router).
@router.post("/add", response_model=MessageResponse)
def add_new_category(category:CategoryBase, db:Session=Depends(get_db), current_user:Users = Depends(require_admin)) -> MessageResponse:
    CategoryService.add_categories(db, category)
    return MessageResponse(msg="Category added successfully")

# Not used by the frontend.
@router.get("/all", response_model=List[CategoryRead])
def see_categories(_:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)) -> list[Category]:
    result = CategoryService.get_categories(db)
    if not result:
        raise HTTPException(status_code=404, detail="No categories found")
    return result

# Not used by the frontend.
@router.put("/update", response_model=MessageResponse)
def update_existing_category(new_category:CategoryUpdate, id:uuid.UUID, db:Session=Depends(get_db), current_user:Users=Depends(require_admin)) -> MessageResponse:
    try:
        CategoryService.update_category(db, id, new_category)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return MessageResponse(msg="Category updated successfully")

# Not used by the frontend.
@router.delete("/delete/{id}", response_model=MessageResponse)
def delete_existing_category(id:uuid.UUID, db:Session=Depends(get_db), current_user:Users=Depends(require_admin)) -> MessageResponse:
    result = CategoryService.delete_category(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Category not found")
    return MessageResponse(msg="Category deleted successfully")