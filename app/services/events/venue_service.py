import uuid

from sqlalchemy.orm import Session

from app.db.models.events import Venue
from app.exception.common import NotFoundError
from app.schema.events import VenueCreate, VenueUpdate


class VenueService:

    # Not company-scoped: venues are shared by every company's concerts.

    @staticmethod
    def add_venue(db: Session, venue: VenueCreate) -> Venue:
        db_venue = Venue(**venue.model_dump())
        db.add(db_venue)
        db.commit()
        db.refresh(db_venue)
        return db_venue

    @staticmethod
    def get_venues(db: Session) -> list[Venue]:
        return db.query(Venue).all()

    @staticmethod
    def get_venue(db: Session, id: uuid.UUID) -> Venue | None:
        return db.get(Venue, id)

    @staticmethod
    def update_venue(db: Session, id: uuid.UUID, data: VenueUpdate) -> Venue:
        db_venue = db.get(Venue, id)
        if not db_venue:
            raise NotFoundError("Venue not found")
        db_venue.name = data.name
        db_venue.address = data.address
        db_venue.city = data.city
        db_venue.country = data.country
        db_venue.total_capacity = data.total_capacity
        db_venue.contact_info = data.contact_info
        db.commit()
        db.refresh(db_venue)
        return db_venue

    @staticmethod
    def delete_venue(db: Session, id: uuid.UUID) -> bool:
        db_venue = db.get(Venue, id)
        if not db_venue:
            return False
        db.delete(db_venue)
        db.commit()
        return True
