import uuid

from sqlalchemy.orm import Session

from app.db.models.marketplace import Category
from app.exception.common import NotFoundError
from app.schema.marketplace import CategoryBase, CategoryUpdate


class CategoryService:

    @staticmethod
    def add_categories(db:Session, category:CategoryBase) -> Category:
        db_category = Category(**category.model_dump())
        db.add(db_category)
        db.commit()
        db.refresh(db_category)
        return db_category

    @staticmethod
    def get_categories(db:Session) -> list[Category]:
        # Was previously annotated `-> CategoryCreate`, which was wrong on two
        # counts: this returns a list, not a single instance, and the actual
        # rows are Category ORM objects, not the CategoryCreate input schema.
        # Corrected while adding the annotations this file was missing.
        return db.query(Category).all()

    @staticmethod
    def update_category(db:Session, id:uuid.UUID, new_category:CategoryUpdate) -> Category:
        db_category = db.get(Category, id)
        if not db_category:
            raise NotFoundError("Category not found")
        db_category.name = new_category.name
        if new_category.is_resale_capped is not None:
            db_category.is_resale_capped = new_category.is_resale_capped
        db.commit()
        db.refresh(db_category)
        return db_category

    @staticmethod
    def delete_category(db:Session, id:uuid.UUID) -> bool:
        db_category = db.get(Category, id)
        if not db_category:
            return False
        db.delete(db_category)
        db.commit()
        return True
