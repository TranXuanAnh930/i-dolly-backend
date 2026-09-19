import uuid

from sqlalchemy.orm import Session

from app.db.models.talent import ManagementCompany
from app.schema.talent import ManagementCompanyBase, ManagementCompanyCreate


class ManagementCompanyService:

    @staticmethod
    def add_company(db: Session, company: ManagementCompanyCreate) -> ManagementCompany | None:
        db_company = ManagementCompany(**company.model_dump())
        if not db_company:
            return None
        db.add(db_company)
        db.commit()
        db.refresh(db_company)
        return db_company

    @staticmethod
    def get_companies(db: Session) -> list[ManagementCompany] | None:
        result = db.query(ManagementCompany).all()
        if not result:
            return None
        return result

    @staticmethod
    def get_company(db: Session, id: uuid.UUID) -> ManagementCompany | None:
        return db.get(ManagementCompany, id)

    @staticmethod
    def update_company(db: Session, id: uuid.UUID, data: ManagementCompanyBase) -> ManagementCompany | None:
        db_company = db.get(ManagementCompany, id)
        if not db_company:
            return None
        db_company.name = data.name
        db_company.description = data.description
        db_company.contact_email = data.contact_email
        db.commit()
        db.refresh(db_company)
        return db_company

    @staticmethod
    def delete_company(db: Session, id: uuid.UUID) -> bool:
        db_company = db.get(ManagementCompany, id)
        if not db_company:
            return False
        db.delete(db_company)
        db.commit()
        return True
