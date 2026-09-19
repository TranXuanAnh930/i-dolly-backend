import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models.marketplace import Category
from app.schema.marketplace import CategoryBase, CategoryUpdate


class CategoryService:

    @staticmethod
    def add_categories(db:Session, category:CategoryBase) -> Category | Literal[False]:
        db_category = Category(**category.model_dump())
        if not db_category:
            return False
        db.add(db_category)
        db.commit()
        db.refresh(db_category)
        return db_category

    @staticmethod
    def get_categories(db:Session) -> list[Category] | Literal[False]:
        # Was previously annotated `-> CategoryCreate`, which was wrong on two
        # counts: this returns a list, not a single instance, and the actual
        # rows are Category ORM objects, not the CategoryCreate input schema.
        # Corrected while adding the annotations this file was missing.
        result = db.query(Category).all()
        if not result:
            return False
        return result

    @staticmethod
    def update_category(db:Session, id:uuid.UUID, new_category:CategoryUpdate) -> Category | Literal[False]:
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
    def delete_category(db:Session, id:uuid.UUID) -> bool:
        db_category = db.get(Category, id)
        if not db_category:
            return False
        db.delete(db_category)
        db.commit()
        return True
