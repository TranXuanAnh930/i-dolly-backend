import uuid

from pydantic import BaseModel, Field


class CartItem(BaseModel):
    quantity : int = Field(..., ge=1)
    product_id : uuid.UUID

class CartOut(CartItem):
    user_id : uuid.UUID

class CartRead(CartOut):
    id : uuid.UUID
    total_price : float
    price : float