import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models.marketplace import ShippingAddress
from app.schema.marketplace import ShippingBase


class ShippingService:

    @staticmethod
    def create_shipping_address(db:Session, user_id:uuid.UUID, data:ShippingBase) -> ShippingAddress | None:
        address = ShippingAddress(**data.model_dump(), user_id=user_id)
        if not address:
            return None
        db.add(address)
        db.commit()
        db.refresh(address)
        return address

    @staticmethod
    def fetch_address(db:Session, user_id:uuid.UUID) -> list[ShippingAddress] | None:
        address = db.query(ShippingAddress).filter(ShippingAddress.user_id==user_id).all()
        if not address:
            return None
        return address

    @staticmethod
    def get_address_by_id(db:Session, address_id:uuid.UUID) -> ShippingAddress | None:
        address = db.query(ShippingAddress).filter(ShippingAddress.id==address_id).first()
        if not address:
            return None
        return address

    @staticmethod
    def update_address(db:Session, user_id:uuid.UUID, data:ShippingBase, address_id:uuid.UUID) -> ShippingAddress | None:
        address = db.query(ShippingAddress).filter(ShippingAddress.id==address_id, user_id==user_id).first()
        if not address:
            return None
        address.address_line1 = data.address_line1
        address.address_line2 = data.address_line2
        address.city = data.city
        address.postal_code = data.postal_code
        address.state = data.state
        address.country = data.country
        db.add(address)
        db.commit()
        db.refresh(address)
        return address

    @staticmethod
    def delete_address(db:Session, user_id:uuid.UUID, address_id:uuid.UUID) -> Literal[True] | None:
        address = db.query(ShippingAddress).filter(ShippingAddress.id==address_id, user_id==user_id).first()
        if not address:
            return None
        db.delete(address)
        db.commit()
        return True
