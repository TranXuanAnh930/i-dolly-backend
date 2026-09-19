import uuid

from sqlalchemy.orm import Session

from app.db.models.talent import IdolColor
from app.exception.common import NotFoundError
from app.schema.talent import IdolColorBase, IdolColorCreate


class IdolColorService:

    @staticmethod
    def add_idol_color(db: Session, color: IdolColorCreate) -> IdolColor:
        db_color = IdolColor(**color.model_dump())
        db.add(db_color)
        db.commit()
        db.refresh(db_color)
        return db_color

    @staticmethod
    def get_idol_colors(db: Session) -> list[IdolColor]:
        return db.query(IdolColor).all()

    @staticmethod
    def update_idol_color(db: Session, id: uuid.UUID, data: IdolColorBase) -> IdolColor:
        db_color = db.get(IdolColor, id)
        if not db_color:
            raise NotFoundError("Idol color not found")
        db_color.name = data.name
        db_color.hex_code = data.hex_code
        db.commit()
        db.refresh(db_color)
        return db_color

    @staticmethod
    def delete_idol_color(db: Session, id: uuid.UUID) -> bool:
        db_color = db.get(IdolColor, id)
        if not db_color:
            return False
        db.delete(db_color)
        db.commit()
        return True
