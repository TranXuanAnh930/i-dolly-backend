import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ShippingBase(BaseModel):
    address_line1:str = Field(..., min_length=1, max_length=300)
    address_line2:str | None = Field(None, max_length=300)
    city:str = Field(..., min_length=1, max_length=100)
    postal_code:str = Field(..., min_length=1, max_length=20)
    state:str = Field(..., min_length=1, max_length=100)
    country:str = Field(..., min_length=1, max_length=100)

class ShippingAddress(ShippingBase):
    id:uuid.UUID
    user_id:uuid.UUID

    model_config = {"from_attributes" : True}

class ShippingStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"

class ShippingStatusResponse(BaseModel):
    status : ShippingStatus
    # When the status last changed; set explicitly by OrderService on each status update.
    updated_at : datetime

    model_config = {"from_attributes" : True}