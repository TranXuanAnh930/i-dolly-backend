import uuid

from sqlalchemy.orm import Session

from app.db.models.management_company import ManagementCompany
from app.schema.management_company import ManagementCompanyBase, ManagementCompanyCreate


def add_company(db: Session, company: ManagementCompanyCreate):
    db_company = ManagementCompany(**company.model_dump())
    if not db_company:
        return False
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company

def get_companies(db: Session):
    result = db.query(ManagementCompany).all()
    if not result:
        return False
    return result

def get_company(db: Session, id: uuid.UUID):
    return db.get(ManagementCompany, id)

def update_company(db: Session, id: uuid.UUID, data: ManagementCompanyBase):
    db_company = db.get(ManagementCompany, id)
    if not db_company:
        return False
    db_company.name = data.name
    db_company.description = data.description
    db_company.contact_email = data.contact_email
    db.commit()
    db.refresh(db_company)
    return db_company

def delete_company(db: Session, id: uuid.UUID):
    db_company = db.get(ManagementCompany, id)
    if not db_company:
        return False
    db.delete(db_company)
    db.commit()
    return True
