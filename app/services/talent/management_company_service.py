import uuid

from sqlalchemy.orm import Session

from app.db.models.talent import ManagementCompany
from app.exception.common import NotFoundError
from app.schema.talent import ManagementCompanyBase, ManagementCompanyCreate


class ManagementCompanyService:

    @staticmethod
    def add_company(db: Session, company: ManagementCompanyCreate) -> ManagementCompany:
        db_company = ManagementCompany(**company.model_dump())
        db.add(db_company)
        db.commit()
        db.refresh(db_company)
        return db_company

    @staticmethod
    def get_companies(db: Session) -> list[ManagementCompany]:
        return db.query(ManagementCompany).all()

    @staticmethod
    def get_company(db: Session, id: uuid.UUID) -> ManagementCompany | None:
        return db.get(ManagementCompany, id)

    @staticmethod
    def update_company(db: Session, id: uuid.UUID, data: ManagementCompanyBase) -> ManagementCompany:
        db_company = db.get(ManagementCompany, id)
        if not db_company:
            raise NotFoundError("Management company not found")
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
