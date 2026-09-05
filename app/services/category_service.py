from sqlalchemy.orm import Session
from app.schema.category import CategoryBase, CategoryCreate, CategoryUpdate
from app.db.models.category import Category

def add_categories(db:Session, category:CategoryBase):
    db_category = Category(**category.model_dump())
    if not db_category:
        return False
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category

def get_categories(db:Session) -> CategoryCreate:
    result = db.query(Category).all()
    if not result:
        return False
    return result

def update_category(db:Session, id:int, new_category:CategoryUpdate):
    db_category = db.get(Category, id)
    if not db_category:
        return False
    db_category.name = new_category.name
    if new_category.is_resale_capped is not None:
        db_category.is_resale_capped = new_category.is_resale_capped
    db.commit()
    db.refresh(db_category)
    return db_category

def delete_category(db:Session, id:int):
    db_category = db.get(Category, id)
    if not db_category:
        return False
    db.delete(db_category)
    db.commit()
    return True
