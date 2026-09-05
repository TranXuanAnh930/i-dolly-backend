import uuid
from sqlalchemy.orm import Session
from app.schema.idol_color import IdolColorBase, IdolColorCreate
from app.db.models.idol_color import IdolColor

def add_idol_color(db: Session, color: IdolColorCreate):
    db_color = IdolColor(**color.model_dump())
    if not db_color:
        return False
    db.add(db_color)
    db.commit()
    db.refresh(db_color)
    return db_color

def get_idol_colors(db: Session):
    result = db.query(IdolColor).all()
    if not result:
        return False
    return result

def update_idol_color(db: Session, id: uuid.UUID, data: IdolColorBase):
    db_color = db.get(IdolColor, id)
    if not db_color:
        return False
    db_color.name = data.name
    db_color.hex_code = data.hex_code
    db.commit()
    db.refresh(db_color)
    return db_color

def delete_idol_color(db: Session, id: uuid.UUID):
    db_color = db.get(IdolColor, id)
    if not db_color:
        return False
    db.delete(db_color)
    db.commit()
    return True
