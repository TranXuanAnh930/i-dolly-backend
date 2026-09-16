import uuid

from sqlalchemy.orm import Session

from app.db.models.marketplace import Category
from app.schema.marketplace import CategoryBase, CategoryCreate, CategoryUpdate


class CategoryService:

    @staticmethod
    def add_categories(db:Session, category:CategoryBase):
        db_category = Category(**category.model_dump())
        if not db_category:
            return False
        db.add(db_category)
        db.commit()
        db.refresh(db_category)
        return db_category

    @staticmethod
    def get_categories(db:Session) -> CategoryCreate:
        result = db.query(Category).all()
        if not result:
            return False
        return result

    @staticmethod
    def update_category(db:Session, id:uuid.UUID, new_category:CategoryUpdate):
        db_category = db.get(Category, id)
        if not db_category:
            return False
        db_category.name = new_category.name
        if new_category.is_resale_capped is not None:
            db_category.is_resale_capped = new_category.is_resale_capped
        db.commit()
        db.refresh(db_category)
        return db_category

    @staticmethod
    def delete_category(db:Session, id:uuid.UUID):
        db_category = db.get(Category, id)
        if not db_category:
            return False
        db.delete(db_category)
        db.commit()
        return True
